"""OpenRouter image adapter using the Image API (POST https://openrouter.ai/api/v1/images).

One call per image (n=1). Reference images go in ``input_references`` as base64 data URLs,
in the order the prompt numbers them: identity, objects (the guide's colour section), style.
The image is read from ``data[0].b64_json``; ``usage.cost`` is the USD actually charged (kept
even when the image is unusable; None when OpenRouter reports no amount, so the registry charges
the estimate). A 502 means the generation failed and was not billed.
Network and service errors (connection, timeout, 429, 5xx) retry the same call NETWORK_RETRIES
times with backoff, then fail as ImageNetworkError, which is never an image attempt; HTTP 402
(no credits) is ImageCreditsError and stops the whole batch (2026-10-21).

The model (2026-10-21): openai/gpt-image-2 (the default). OpenAI's image models take a pixel
``size`` and a ``quality`` instead of aspect_ratio/resolution: three sizes, 1024x1024,
1024x1536 (portrait) and 1536x1024 (landscape); our 4:5 and 3:4 canvases are made at 1024x1536
and trimmed at the top and bottom by the app (the prompt keeps the text clear of those edges).
Quality "high" (small German text needs it), output PNG, up to 16 input images (we send at most
14). UNVERIFIED until the first paid run: confirm the parameters with
GET https://openrouter.ai/api/v1/images/models/openai/gpt-image-2/endpoints and record the
real ``usage.cost`` (the estimate below is OpenAI's token price for gpt-image models).
Other models (any non-OpenAI id) keep the generic aspect_ratio/resolution request.
See https://openrouter.ai/docs/features/multimodal/image-generation.
"""

import base64
import binascii
import io
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, UnidentifiedImageError

from content_automation.ai.image import (
    ALL_ASPECT_RATIOS,
    ASPECT_RATIOS,
    IMAGE_SIZES,
    NETWORK_BACKOFF_S,
    NETWORK_RETRIES,
    GeneratedImage,
    ImageCreditsError,
    ImageNetworkError,
    ImageProviderError,
    ImageRequest,
    ImageResult,
    ImageTimeoutError,
    ProviderCapabilities,
)
from content_automation.core.config import Settings
from content_automation.core.retry import OperationTimeoutError, run_with_timeout

API_URL = "https://openrouter.ai/api/v1/images"
MAX_INPUT_REFERENCES = 14
DEFAULT_IDENTITY_REFS = 4
DEFAULT_MODEL = "openai/gpt-image-2"
# Estimate, not calibrated: high quality at 1024x1536 is about 6,240 output tokens at $40 per
# million (~$0.25), plus up to four reference images as input (~$0.03): ~$0.28 per image, the
# same at every IMAGE_DESIGN_SIZE (the model has one size per aspect).
EST_COST_USD_PER_IMAGE = {"1K": 0.28, "2K": 0.28, "4K": 0.28}
# Generic models (aspect_ratio/resolution), kept for an explicit IMAGE_MODEL override only.
EST_COST_USD_GENERIC = {"1K": 0.067, "2K": 0.101, "4K": 0.151}
OPENAI_SIZES = {"square": "1024x1024", "portrait": "1024x1536", "landscape": "1536x1024"}
OPENAI_QUALITY = "high"
MISSING_KEY = "OPENROUTER_API_KEY missing: add it to .env to use IMAGE_PROVIDER=openrouter."
_MIME_BY_SUFFIX = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                   ".webp": "image/webp"}
_MIME_BY_FORMAT = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
_DETAIL_LIMIT = 300


def is_openai(model: str) -> bool:
    return model.startswith("openai/")


def openai_size(aspect: str) -> str:
    """The OpenAI size for an aspect: the nearest of square, portrait and landscape."""
    left, _, right = aspect.partition(":")
    ratio = int(left) / int(right)
    return OPENAI_SIZES["square" if 0.9 <= ratio <= 1.1 else
                        "portrait" if ratio < 1 else "landscape"]


def capabilities_for(identity_max: int, model: str = DEFAULT_MODEL) -> ProviderCapabilities:
    """All reference images share one budget of 14; identity is capped by the setting."""
    openai = is_openai(model)
    return ProviderCapabilities(
        max_identity_refs=min(identity_max, MAX_INPUT_REFERENCES),
        max_object_refs=MAX_INPUT_REFERENCES,
        max_style_refs=MAX_INPUT_REFERENCES,
        max_total_refs=MAX_INPUT_REFERENCES,
        aspect_ratios=frozenset(ALL_ASPECT_RATIOS if openai else ASPECT_RATIOS),
        image_sizes=frozenset(IMAGE_SIZES),
        max_images_per_call=1,
        est_cost_usd_per_image=EST_COST_USD_PER_IMAGE if openai else EST_COST_USD_GENERIC,
        draws_text=True,  # the model draws the headline, body and CTA itself (designer mode)
    )


class OpenRouterImageProvider:
    name = "openrouter"

    def __init__(
        self,
        api_key: str | None,
        *,
        model: str = DEFAULT_MODEL,
        identity_max: int = DEFAULT_IDENTITY_REFS,
        timeout_s: float = 120.0,
        max_retries: int = 1,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._api_key = api_key
        self.capabilities = capabilities_for(identity_max, model)
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

    def generate(self, request: ImageRequest, model: str) -> ImageResult:
        if not self._api_key:
            raise ImageProviderError(MISSING_KEY)
        body: dict[str, Any] = {"model": model, "prompt": request.prompt, "n": 1}
        if is_openai(model):  # pixel size and quality, PNG out (see the module note)
            body |= {"size": openai_size(request.aspect_ratio), "quality": OPENAI_QUALITY,
                     "output_format": "png"}
        else:
            body |= {"aspect_ratio": request.aspect_ratio, "resolution": request.image_size}
        references = _input_references(request)
        if references:
            body["input_references"] = references
        headers = {"Authorization": f"Bearer {self._api_key}"}
        images: list[GeneratedImage] = []
        request_ids: list[str] = []
        cost: float | None = None
        unreported = False  # an amount missing: the registry charges the estimate instead
        with httpx.Client(timeout=self._timeout_s, transport=self._transport) as client:
            for index in range(1, request.count + 1):
                try:
                    payload = self._call_once(client, headers, body)
                    charged = _usage_cost(payload)  # billed even if the image is unusable
                    if charged is None:
                        unreported = True
                    else:
                        cost = round((cost or 0.0) + charged, 6)
                    images.append(_extract_image(payload))
                except ImageProviderError as error:
                    error.args = (f"Image {index} of {request.count}: {error}",)
                    error.cost_usd = None if unreported else cost  # what was billed so far
                    raise
                if isinstance(payload.get("id"), str):
                    request_ids.append(payload["id"])
        return ImageResult(
            images=images,
            provider=self.name,
            model=model,
            provider_request_ids=request_ids,
            cost_usd=None if unreported else cost,
        )

    def _call_once(
        self, client: httpx.Client, headers: dict[str, str], body: dict[str, Any]
    ) -> dict[str, Any]:
        """One API call, retried on its own so earlier (paid) images are never redone: a network
        or service error retries the same call (at least NETWORK_RETRIES times, with backoff),
        then ImageNetworkError (not retryable: the job retry must not repeat it)."""

        def call() -> dict[str, Any]:
            try:
                response = client.post(API_URL, headers=headers, json=body)
            except httpx.TimeoutException:
                raise ImageTimeoutError("OpenRouter did not respond in time.",
                                        retryable=True) from None
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

        sleep = self._sleep or time.sleep
        retries = max(self._max_retries, NETWORK_RETRIES)
        failure: ImageProviderError | None = None
        for attempt in range(retries + 1):
            try:
                return run_with_timeout(call, self._timeout_s + 5)
            except OperationTimeoutError as error:
                failure = ImageTimeoutError(f"OpenRouter did not respond in time: {error}")
            except ImageProviderError as error:
                if not error.retryable:
                    raise
                failure = error
            if attempt < retries:
                sleep(min(NETWORK_BACKOFF_S * 2**attempt, 30.0))
        assert failure is not None
        raise ImageNetworkError(f"{failure} (the same call was tried {retries + 1} times; a "
                                "network error, not an image attempt)")


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
        return ImageCreditsError(
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


def _usage_cost(payload: dict[str, Any]) -> float | None:
    """The USD OpenRouter charged for this call (None: no amount in the response)."""
    usage = payload.get("usage")
    cost = usage.get("cost") if isinstance(usage, dict) else None
    return float(cost) if isinstance(cost, int | float) else None


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
        model=settings.image_model,
        identity_max=settings.image_identity_refs_max,
        timeout_s=settings.image_timeout_ms / 1000,
        max_retries=settings.image_max_retries,
    )
