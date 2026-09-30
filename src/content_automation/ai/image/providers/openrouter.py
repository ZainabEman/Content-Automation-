"""OpenRouter image adapter using the Image API (POST https://openrouter.ai/api/v1/images).

One call per image (n=1). Reference images go in ``input_references`` as base64 data URLs,
in the order the prompt numbers them: identity, objects (product, then logo), style.
The image is read from ``data[0].b64_json``; ``usage.cost`` is the USD actually charged.
A 502 means the generation failed and was not billed.

Limits for google/gemini-3.1-flash-image, from
GET https://openrouter.ai/api/v1/images/models/google/gemini-3.1-flash-image/endpoints:
resolution 512/1K/2K/4K, n 1-1, input_references 0-14, and all four of our aspect ratios.
See https://openrouter.ai/docs/features/multimodal/image-generation.
"""

import base64
import binascii
import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, UnidentifiedImageError

from content_automation.ai.image import (
    ASPECT_RATIOS,
    IMAGE_SIZES,
    GeneratedImage,
    ImageProviderError,
    ImageRequest,
    ImageResult,
    ImageTimeoutError,
    ProviderCapabilities,
)
from content_automation.core.config import Settings
from content_automation.core.retry import OperationTimeoutError, call_with_retry

API_URL = "https://openrouter.ai/api/v1/images"
MAX_INPUT_REFERENCES = 14
DEFAULT_IDENTITY_REFS = 4
# Output images cost $0.00006 per token (endpoint pricing): about 1120 / 1680 / 2520 tokens
# at 1K / 2K / 4K, the same per-image prices as the Gemini adapter.
EST_COST_USD_PER_IMAGE = {"1K": 0.067, "2K": 0.101, "4K": 0.151}
MISSING_KEY = "OPENROUTER_API_KEY missing: add it to .env to use IMAGE_PROVIDER=openrouter."
_MIME_BY_SUFFIX = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                   ".webp": "image/webp"}
_MIME_BY_FORMAT = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
_DETAIL_LIMIT = 300


def capabilities_for(identity_max: int) -> ProviderCapabilities:
    """All reference images share one budget of 14; identity is capped by the setting."""
    return ProviderCapabilities(
        max_identity_refs=min(identity_max, MAX_INPUT_REFERENCES),
        max_object_refs=MAX_INPUT_REFERENCES,
        max_style_refs=MAX_INPUT_REFERENCES,
        max_total_refs=MAX_INPUT_REFERENCES,
        aspect_ratios=frozenset(ASPECT_RATIOS),
        image_sizes=frozenset(IMAGE_SIZES),
        max_images_per_call=1,
        est_cost_usd_per_image=EST_COST_USD_PER_IMAGE,
    )


class OpenRouterImageProvider:
    name = "openrouter"

    def __init__(
        self,
        api_key: str | None,
        *,
        identity_max: int = DEFAULT_IDENTITY_REFS,
        timeout_s: float = 120.0,
        max_retries: int = 1,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._api_key = api_key
        self.capabilities = capabilities_for(identity_max)
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

    def generate(self, request: ImageRequest, model: str) -> ImageResult:
        if not self._api_key:
            raise ImageProviderError(MISSING_KEY)
        body: dict[str, Any] = {
            "model": model,
            "prompt": request.prompt,
            "aspect_ratio": request.aspect_ratio,
            "resolution": request.image_size,
            "n": 1,
        }
        references = _input_references(request)
        if references:
            body["input_references"] = references
        headers = {"Authorization": f"Bearer {self._api_key}"}
        images: list[GeneratedImage] = []
        request_ids: list[str] = []
        cost: float | None = None
        with httpx.Client(timeout=self._timeout_s, transport=self._transport) as client:
            for index in range(1, request.count + 1):
                try:
                    payload = self._call_once(client, headers, body)
                    images.append(_extract_image(payload))
                except ImageProviderError as error:
                    error.args = (f"Image {index} of {request.count}: {error}",)
                    error.cost_usd = cost  # earlier images were billed
                    raise
                cost = round((cost or 0.0) + _usage_cost(payload), 6)
                if isinstance(payload.get("id"), str):
                    request_ids.append(payload["id"])
        return ImageResult(
            images=images,
            provider=self.name,
            model=model,
            provider_request_ids=request_ids,
            cost_usd=cost,
        )

    def _call_once(
        self, client: httpx.Client, headers: dict[str, str], body: dict[str, Any]
    ) -> dict[str, Any]:
        """One API call, retried on its own so earlier (paid) images are never redone."""

        def call() -> dict[str, Any]:
            try:
                response = client.post(API_URL, headers=headers, json=body)
            except httpx.TimeoutException:
                raise ImageTimeoutError("OpenRouter did not respond in time.") from None
            except httpx.TransportError as error:
                raise ImageProviderError(
                    f"Could not reach OpenRouter ({type(error).__name__}).", retryable=True
                ) from None
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if response.status_code != 200 or not isinstance(payload, dict):
                raise map_error(response.status_code, _error_detail(payload, response.text))
            reported = payload.get("error")
            if reported:
                code = reported.get("code") if isinstance(reported, dict) else None
                raise map_error(code if isinstance(code, int) else 0, _error_detail(payload, ""))
            return payload

        kwargs: dict[str, Any] = {}
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        try:
            return call_with_retry(
                call, timeout_s=self._timeout_s + 5, max_retries=self._max_retries, **kwargs
            )
        except OperationTimeoutError as error:
            raise ImageTimeoutError(f"OpenRouter did not respond in time: {error}") from None
        except ImageProviderError as error:
            # Already retried here; stop the outer job retry from repeating finished images.
            error.retryable = False
            raise


def _input_references(request: ImageRequest) -> list[dict[str, Any]]:
    references = []
    for ref in [*request.identity_refs, *request.object_refs, *request.style_refs]:
        try:
            data = ref.path.read_bytes()
        except OSError:
            raise ImageProviderError(
                f"Reference image not found: {ref.source or ref.path}. Run `ca refs scan`."
            ) from None
        encoded = base64.b64encode(data).decode("ascii")
        references.append({
            "type": "image_url",
            "image_url": {"url": f"data:{_mime_for(ref.path)};base64,{encoded}"},
        })
    return references


def _mime_for(path: Path) -> str:
    mime = _MIME_BY_SUFFIX.get(path.suffix.lower())
    if mime is None:
        raise ImageProviderError(f"Unsupported reference image type: {path.name}.")
    return mime


def _short(text: object) -> str:
    return " ".join(str(text).split())[:_DETAIL_LIMIT]


def _error_detail(payload: object, fallback: str) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return _short(error["message"])
        if isinstance(error, str):
            return _short(error)
    return _short(fallback) or "no details"


def map_error(status: int, detail: str) -> ImageProviderError:
    """429 and 5xx are retryable (502 = the model failed, not billed); other errors are not."""
    if status == 402:
        return ImageProviderError(
            "OpenRouter needs more credits (HTTP 402): add credits at "
            f"https://openrouter.ai/settings/credits. Details: {detail}"
        )
    if status == 401:
        return ImageProviderError(
            "OpenRouter rejected the API key (HTTP 401); check OPENROUTER_API_KEY in .env."
        )
    if status == 400:
        return ImageProviderError(f"OpenRouter rejected the request (HTTP 400): {detail}")
    if status == 429:
        return ImageProviderError(
            f"OpenRouter rate limit reached (HTTP 429): {detail}", retryable=True
        )
    if status == 502:
        return ImageProviderError(
            f"The image model failed (HTTP 502, not billed): {detail}", retryable=True
        )
    if status >= 500:
        return ImageProviderError(
            f"OpenRouter server error (HTTP {status}): {detail}", retryable=True
        )
    label = f"HTTP {status}" if status else "error in response"
    return ImageProviderError(f"OpenRouter rejected the request ({label}): {detail}")


def _usage_cost(payload: dict[str, Any]) -> float:
    usage = payload.get("usage")
    cost = usage.get("cost") if isinstance(usage, dict) else None
    return float(cost) if isinstance(cost, int | float) else 0.0


def _extract_image(payload: dict[str, Any]) -> GeneratedImage:
    data = payload.get("data")
    item = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    raw = item.get("b64_json")
    if not isinstance(raw, str) or not raw:
        raise ImageProviderError(
            "OpenRouter returned no image (often a safety block; try rewording the prompt or "
            "using other reference photos)."
        )
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        image_bytes = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise ImageProviderError(
            "OpenRouter returned image data that is not valid base64."
        ) from None
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image_format = image.format or ""
            image.verify()
    except (OSError, UnidentifiedImageError):
        raise ImageProviderError("OpenRouter returned data that is not a valid image.") from None
    mime = _MIME_BY_FORMAT.get(image_format) or item.get("media_type") or "image/png"
    return GeneratedImage(data=image_bytes, mime_type=str(mime))


def create_provider(settings: Settings | None = None) -> OpenRouterImageProvider:
    if settings is None:
        return OpenRouterImageProvider(api_key=None)
    key = (
        settings.openrouter_api_key.get_secret_value().strip()
        if settings.openrouter_api_key
        else None
    )
    return OpenRouterImageProvider(
        api_key=key or None,
        identity_max=settings.image_identity_refs_max,
        timeout_s=settings.image_timeout_ms / 1000,
        max_retries=settings.image_max_retries,
    )
