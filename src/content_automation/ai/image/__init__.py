"""Image generation capability: the only public entry point for image providers.

App code calls ``generate_image()``; adapters live in ``providers/`` and are chosen
by ``IMAGE_PROVIDER`` (adapter) and ``IMAGE_MODEL`` (model passed to the adapter).
"""

import importlib
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from content_automation.core.config import Settings, load_settings

AspectRatio = Literal["1:1", "4:5", "9:16", "16:9"]
ImageSize = Literal["1K", "2K", "4K"]
ASPECT_RATIOS: tuple[AspectRatio, ...] = ("1:1", "4:5", "9:16", "16:9")
IMAGE_SIZES: tuple[ImageSize, ...] = ("1K", "2K", "4K")
MAX_COUNT = 4

# Provider name -> adapter module. Adding a provider = one adapter file + one line here.
_ADAPTERS: dict[str, str] = {
    "mock": "content_automation.ai.image.providers.mock",
}


class ImageError(Exception):
    """Base class for image capability errors."""

    retryable = False


class ImageRequestError(ImageError, ValueError):
    """The request is invalid or exceeds the selected provider's limits."""


class UnknownImageProviderError(ImageError):
    """IMAGE_PROVIDER names an adapter that does not exist."""


class ImageProviderError(ImageError):
    """The provider call failed; ``retryable`` marks temporary failures."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ImageTimeoutError(ImageProviderError, TimeoutError):
    """The provider did not respond in time."""


class ReferenceImage(BaseModel):
    """A reference file plus its stable asset ID from the reference library."""

    model_config = ConfigDict(frozen=True)

    asset_id: str = Field(min_length=1)
    path: Path


class ImageRequest(BaseModel):
    """What to generate. Reference categories are kept as separate lists.

    Adapters must attach reference images in this order: identity_refs, then
    object_refs, then style_refs, because prompts number the images that way.
    """

    model_config = ConfigDict(frozen=True)

    prompt: str = Field(min_length=1)
    aspect_ratio: AspectRatio = "1:1"
    image_size: ImageSize = "1K"
    count: int = Field(default=1, ge=1, le=MAX_COUNT)
    identity_refs: list[ReferenceImage] = Field(default_factory=list)
    object_refs: list[ReferenceImage] = Field(default_factory=list)  # product + brand
    style_refs: list[ReferenceImage] = Field(default_factory=list)  # creative


class GeneratedImage(BaseModel):
    data: bytes
    mime_type: str


class ImageResult(BaseModel):
    images: list[GeneratedImage]
    provider: str
    model: str
    provider_request_ids: list[str] = Field(default_factory=list)


class ProviderCapabilities(BaseModel):
    """Limits an adapter declares; requests over them are rejected before any call."""

    model_config = ConfigDict(frozen=True)

    max_identity_refs: int
    max_object_refs: int
    max_style_refs: int
    aspect_ratios: frozenset[str]
    image_sizes: frozenset[str]
    max_count: int = MAX_COUNT
    est_cost_usd_per_image: dict[str, float] = Field(default_factory=dict)


class ImageProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    def generate(self, request: ImageRequest, model: str) -> ImageResult: ...


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


def get_provider(name: str) -> ImageProvider:
    """Load the adapter registered under ``name``."""
    module_name = _ADAPTERS.get(name)
    if module_name is None:
        raise UnknownImageProviderError(
            f"Image provider '{name}' is not available. Set IMAGE_PROVIDER to one of: "
            f"{', '.join(available_providers())}."
        )
    module = importlib.import_module(module_name)
    provider: ImageProvider = module.create_provider()
    return provider


def validate_request(request: ImageRequest, capabilities: ProviderCapabilities) -> None:
    problems: list[str] = []
    if request.aspect_ratio not in capabilities.aspect_ratios:
        problems.append(f"aspect ratio {request.aspect_ratio} is not supported")
    if request.image_size not in capabilities.image_sizes:
        problems.append(f"image size {request.image_size} is not supported")
    if request.count > capabilities.max_count:
        problems.append(f"{request.count} images requested (max {capabilities.max_count})")
    for label, refs, limit in (
        ("identity", request.identity_refs, capabilities.max_identity_refs),
        ("object", request.object_refs, capabilities.max_object_refs),
        ("style", request.style_refs, capabilities.max_style_refs),
    ):
        if len(refs) > limit:
            problems.append(f"{len(refs)} {label} references (max {limit})")
    if problems:
        raise ImageRequestError("Request exceeds provider limits: " + "; ".join(problems) + ".")


def estimate_cost_usd(request: ImageRequest, settings: Settings | None = None) -> float:
    settings = settings or load_settings()
    capabilities = get_provider(settings.image_provider).capabilities
    per_image = capabilities.est_cost_usd_per_image.get(request.image_size, 0.0)
    return round(per_image * request.count, 4)


def generate_image(request: ImageRequest, settings: Settings | None = None) -> ImageResult:
    """Validate the request against the selected adapter, then generate the images."""
    settings = settings or load_settings()
    provider = get_provider(settings.image_provider)
    validate_request(request, provider.capabilities)
    result = provider.generate(request, settings.image_model)
    if len(result.images) != request.count:
        raise ImageProviderError(
            f"Provider returned {len(result.images)} images; {request.count} were requested."
        )
    return result
