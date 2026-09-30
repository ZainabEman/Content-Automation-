"""Gemini image adapter using the Interactions API (google-genai >= 2.3).

One ``client.interactions.create`` call per image. Input is the prompt as a text
part followed by the reference images (identity, object, style) as base64 parts.
The image is read from ``output_image``, falling back to ``model_output`` steps.
See https://ai.google.dev/gemini-api/docs/image-generation.
"""

import base64
import binascii
import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

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

MISSING_KEY = "GEMINI_API_KEY missing: add it to .env to use IMAGE_PROVIDER=gemini."
_MIME_BY_SUFFIX = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                   ".webp": "image/webp"}
_MIME_BY_FORMAT = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
_DETAIL_LIMIT = 300

ClientFactory = Callable[[str], Any]


def _google_client(api_key: str) -> Any:
    from google import genai

    return genai.Client(api_key=api_key)


class GeminiImageProvider:
    """Limits are those of gemini-3.1-flash-image."""

    name = "gemini"
    capabilities = ProviderCapabilities(
        max_identity_refs=4,
        max_object_refs=10,
        max_style_refs=3,
        max_object_and_style_refs=10,
        aspect_ratios=frozenset(ASPECT_RATIOS),
        image_sizes=frozenset(IMAGE_SIZES),
        est_cost_usd_per_image={"1K": 0.067, "2K": 0.101, "4K": 0.151},
    )

    def __init__(
        self,
        api_key: str | None,
        *,
        timeout_s: float = 120.0,
        max_retries: int = 1,
        client_factory: ClientFactory | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._client_factory = client_factory or _google_client
        self._sleep = sleep

    def generate(self, request: ImageRequest, model: str) -> ImageResult:
        if not self._api_key:
            raise ImageProviderError(MISSING_KEY)
        parts = _input_parts(request)
        client = self._client_factory(self._api_key)
        response_format = {
            "type": "image",
            "aspect_ratio": request.aspect_ratio,
            "image_size": request.image_size,
        }
        images: list[GeneratedImage] = []
        request_ids: list[str] = []
        for index in range(1, request.count + 1):
            interaction = self._call_once(client, model, parts, response_format)
            request_ids.append(str(getattr(interaction, "id", "") or ""))
            try:
                images.append(_extract_image(interaction))
            except ImageProviderError as error:
                raise ImageProviderError(f"Image {index} of {request.count}: {error}") from None
        return ImageResult(
            images=images, provider=self.name, model=model, provider_request_ids=request_ids
        )

    def _call_once(
        self, client: Any, model: str, parts: list[dict[str, str]], response_format: dict[str, str]
    ) -> Any:
        """One API call, retried on its own so earlier (paid) images are never redone."""

        def call() -> Any:
            try:
                return client.interactions.create(
                    model=model,
                    input=parts,
                    response_format=response_format,
                    timeout=self._timeout_s,
                )
            except Exception as error:
                raise map_error(error) from None

        kwargs: dict[str, Any] = {}
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        try:
            return call_with_retry(
                call,
                timeout_s=self._timeout_s + 5,
                max_retries=self._max_retries,
                **kwargs,
            )
        except OperationTimeoutError as error:
            raise ImageTimeoutError(f"Gemini did not respond in time: {error}") from None
        except ImageProviderError as error:
            # Already retried here; stop the outer job retry from repeating finished images.
            error.retryable = False
            raise


def _input_parts(request: ImageRequest) -> list[dict[str, str]]:
    parts = [{"type": "text", "text": request.prompt}]
    for ref in [*request.identity_refs, *request.object_refs, *request.style_refs]:
        try:
            data = ref.path.read_bytes()
        except OSError:
            raise ImageProviderError(
                f"Reference image not found: {ref.source or ref.path}. Run `ca refs scan`."
            ) from None
        parts.append({
            "type": "image",
            "data": base64.b64encode(data).decode("ascii"),
            "mime_type": _mime_for(ref.path),
        })
    return parts


def _mime_for(path: Path) -> str:
    mime = _MIME_BY_SUFFIX.get(path.suffix.lower())
    if mime is None:
        raise ImageProviderError(f"Unsupported reference image type: {path.name}.")
    return mime


def _short(text: object) -> str:
    return " ".join(str(text).split())[:_DETAIL_LIMIT]


def map_error(error: Exception) -> ImageProviderError:
    """Translate SDK/HTTP errors: 429 and 5xx retryable; 4xx and others not."""
    if isinstance(error, ImageProviderError):
        return error
    name = type(error).__name__
    detail = _short(error) or name
    if isinstance(error, TimeoutError) or "Timeout" in name:
        return ImageTimeoutError(f"Gemini did not respond in time: {detail}")
    status = getattr(error, "status_code", None)
    if not isinstance(status, int):
        status = getattr(error, "code", None)
    if isinstance(status, int):
        if status == 429:
            return ImageProviderError(
                f"Gemini rate limit or quota reached (HTTP 429): {detail}", retryable=True
            )
        if status >= 500:
            return ImageProviderError(
                f"Gemini server error (HTTP {status}): {detail}", retryable=True
            )
        if status in (401, 403):
            return ImageProviderError(
                f"Gemini rejected the API key (HTTP {status}); check GEMINI_API_KEY."
            )
        return ImageProviderError(f"Gemini rejected the request (HTTP {status}): {detail}")
    if "Connection" in name:
        return ImageProviderError(f"Could not reach Gemini: {detail}", retryable=True)
    return ImageProviderError(f"Gemini call failed ({name}): {detail}")


def _find_image_block(interaction: Any) -> Any:
    image = getattr(interaction, "output_image", None)
    if image is not None and getattr(image, "data", None):
        return image
    for step in reversed(getattr(interaction, "steps", None) or []):
        if getattr(step, "type", None) != "model_output":
            continue
        for block in reversed(getattr(step, "content", None) or []):
            if getattr(block, "type", None) == "image" and getattr(block, "data", None):
                return block
    return None


def _no_image_reason(interaction: Any) -> str:
    reasons = [f"status: {getattr(interaction, 'status', 'unknown')}"]
    for error in getattr(interaction, "errors", None) or []:
        if getattr(error, "message", None):
            reasons.append(_short(error.message))
    for step in getattr(interaction, "steps", None) or []:
        step_error = getattr(step, "error", None)
        if step_error is not None and getattr(step_error, "message", None):
            reasons.append(_short(step_error.message))
    text = getattr(interaction, "output_text", None)
    if text:
        reasons.append(f"model said: {_short(text)}")
    return "; ".join(reasons)


def _extract_image(interaction: Any) -> GeneratedImage:
    block = _find_image_block(interaction)
    if block is None:
        raise ImageProviderError(
            "Gemini returned no image (often a safety block; try rewording the prompt or "
            f"using other reference photos). Details: {_no_image_reason(interaction)}"
        )
    raw = block.data
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise ImageProviderError("Gemini returned image data that is not valid base64.") from None
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format or ""
            image.verify()
    except (OSError, UnidentifiedImageError):
        raise ImageProviderError("Gemini returned data that is not a valid image.") from None
    mime = _MIME_BY_FORMAT.get(image_format) or getattr(block, "mime_type", None) or "image/png"
    return GeneratedImage(data=data, mime_type=str(mime))


def create_provider(settings: Settings | None = None) -> GeminiImageProvider:
    if settings is None:
        return GeminiImageProvider(api_key=None)
    key = settings.gemini_api_key.get_secret_value().strip() if settings.gemini_api_key else None
    return GeminiImageProvider(
        api_key=key or None,
        timeout_s=settings.image_timeout_ms / 1000,
        max_retries=settings.image_max_retries,
    )
