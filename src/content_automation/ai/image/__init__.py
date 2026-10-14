"""Image generation capability: the only public entry point for image providers.

App code calls ``generate_image()``; adapters live in ``providers/`` and are chosen
by ``IMAGE_PROVIDER`` (adapter) and ``IMAGE_MODEL`` (model passed to the adapter).
"""

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

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
    "openrouter": "content_automation.ai.image.providers.openrouter",
    "comfyui": "content_automation.ai.image.providers.comfyui",
}


class ImageError(Exception):
    """Base class for image capability errors."""

    retryable = False


class ImageRequestError(ImageError, ValueError):
    """The request is invalid or exceeds the selected provider's limits."""


class UnknownImageProviderError(ImageError):
    """IMAGE_PROVIDER names an adapter that does not exist."""


class ImageProviderError(ImageError):
    """The provider call failed; ``retryable`` marks temporary failures and
    ``cost_usd`` what earlier images of the same request were already billed."""

    def __init__(
        self, message: str, *, retryable: bool = False, cost_usd: float | None = None
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.cost_usd = cost_usd


class ImageTimeoutError(ImageProviderError, TimeoutError):
    """The provider did not respond in time."""


class ReferenceImage(BaseModel):
    """A reference file plus its stable asset ID from the reference library."""

    model_config = ConfigDict(frozen=True)

    asset_id: str = Field(min_length=1)
    path: Path
    source: str = ""  # original file, e.g. identity/person_01/1.jpg (for display)
    people: bool | None = None  # style tags from the reference library; None = untagged
    logo: bool | None = None


class ImageRequest(BaseModel):
    """What to generate. Reference categories are kept as separate lists.

    Adapters must attach reference images in this order: identity_refs, then
    object_refs, then style_refs, because prompts number the images that way.
    The logo is never sent: the app pastes the real file onto the result.
    """

    model_config = ConfigDict(frozen=True)

    prompt: str = Field(min_length=1)
    aspect_ratio: AspectRatio = "1:1"
    image_size: ImageSize = "1K"
    count: int = Field(default=1, ge=1, le=MAX_COUNT)
    identity_refs: list[ReferenceImage] = Field(default_factory=list)
    object_refs: list[ReferenceImage] = Field(default_factory=list)  # products
    style_refs: list[ReferenceImage] = Field(default_factory=list)  # creative
    # The identity person is shown. Providers with a trained identity (identity_prompt) apply
    # it only then; the others get identity_refs instead.
    person: bool = False


class GeneratedImage(BaseModel):
    data: bytes
    mime_type: str


class ImageResult(BaseModel):
    images: list[GeneratedImage]
    provider: str
    model: str
    provider_request_ids: list[str] = Field(default_factory=list)
    cost_usd: float | None = None  # actual charge, when the provider reports it
    # Provider-reported numbers kept in the job record, e.g. RunPod delayTimeMs and
    # executionTimeMs, and the seed of each image.
    metrics: dict[str, float] = Field(default_factory=dict)


class ProviderCapabilities(BaseModel):
    """Limits an adapter declares; requests over them are rejected before any call."""

    model_config = ConfigDict(frozen=True)

    max_identity_refs: int
    max_object_refs: int
    max_style_refs: int
    max_object_and_style_refs: int | None = None  # combined cap, if the model has one
    max_total_refs: int | None = None  # cap on all reference images together, if any
    aspect_ratios: frozenset[str]
    image_sizes: frozenset[str]
    max_count: int = MAX_COUNT
    max_images_per_call: int = 1  # count N may take several provider calls
    est_cost_usd_per_image: dict[str, float] = Field(default_factory=dict)
    # The model renders on-image text (headline, CTA) itself; False: the app overlays it
    # (workflows/text_overlay.py, TEXT_OVERLAY=auto).
    draws_text: bool = True
    # Added once per request on top of the per-image price (e.g. a GPU cold start).
    est_cost_usd_per_request: float = 0.0
    cost_basis: str = ""  # how the estimate is made, shown in the dry run; "" = provider price
    # A trained identity (LoRA): the prompt text that calls it up. Then no identity photos
    # are sent and max_identity_refs is 0.
    identity_prompt: str | None = None
    # The adapter's own time budget per image (a provider that is polled); None: the
    # IMAGE_TIMEOUT_MS based budget.
    timeout_s: float | None = None
    # Make every image of a package back-to-back (one GPU cold start), then the person checks;
    # False: the build stops for the person check after each image with the person.
    batch_images: bool = False


class ImageProvider(Protocol):
    """Adapter contract. Each adapter module exposes ``create_provider(settings)``;
    settings may be None when only the capabilities are needed (no call is made)."""

    name: str
    capabilities: ProviderCapabilities

    def generate(self, request: ImageRequest, model: str) -> ImageResult: ...


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


def get_provider(name: str, settings: Settings | None = None) -> ImageProvider:
    """Load the adapter registered under ``name``; creating it makes no provider call."""
    module_name = _ADAPTERS.get(name)
    if module_name is None:
        raise UnknownImageProviderError(
            f"Image provider '{name}' is not available. Set IMAGE_PROVIDER to one of: "
            f"{', '.join(available_providers())}."
        )
    module = importlib.import_module(module_name)
    provider: ImageProvider = module.create_provider(settings)
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
    combined = len(request.object_refs) + len(request.style_refs)
    combined_limit = capabilities.max_object_and_style_refs
    if combined_limit is not None and combined > combined_limit:
        problems.append(
            f"{combined} product/brand/style references together (max {combined_limit})"
        )
    total = len(request.identity_refs) + combined
    if capabilities.max_total_refs is not None and total > capabilities.max_total_refs:
        problems.append(f"{total} reference images in total (max {capabilities.max_total_refs})")
    if problems:
        raise ImageRequestError("Request exceeds provider limits: " + "; ".join(problems) + ".")


def estimate_cost_usd(
    request: ImageRequest, settings: Settings | None = None, *, cold_start: bool = True
) -> float:
    """cold_start=False: a request that follows another one on a warm worker, so the
    per-request cost (est_cost_usd_per_request) is not counted again."""
    settings = settings or load_settings(require_credentials=False)
    capabilities = get_provider(settings.image_provider, settings).capabilities
    per_image = capabilities.est_cost_usd_per_image.get(request.image_size, 0.0)
    per_request = capabilities.est_cost_usd_per_request if cold_start else 0.0
    return round(per_image * request.count + per_request, 4)


def generate_image(request: ImageRequest, settings: Settings | None = None) -> ImageResult:
    """Validate the request against the selected adapter, then generate the images."""
    settings = settings or load_settings()
    provider = get_provider(settings.image_provider, settings)
    validate_request(request, provider.capabilities)
    result = provider.generate(request, settings.image_model)
    if len(result.images) != request.count:
        raise ImageProviderError(
            f"Provider returned {len(result.images)} images; {request.count} were requested."
        )
    return result


# config/comfyui.json helpers for doctor and lora, so no app module imports the adapter itself.
# The adapter imports this package, so it is loaded on first use, not here.
_COMFYUI_EXPORTS = {
    "ComfyUIConfig": "ComfyUIConfig",
    "is_unset": "is_unset",
    "load_comfyui_config": "load_config",
    "load_comfyui_workflow": "load_workflow",
    "comfyui_model_file_problems": "model_file_problems",
}

if TYPE_CHECKING:
    from content_automation.ai.image.providers import comfyui as _comfyui

    ComfyUIConfig = _comfyui.ComfyUIConfig
    is_unset = _comfyui.is_unset
    load_comfyui_config = _comfyui.load_config
    load_comfyui_workflow = _comfyui.load_workflow
    comfyui_model_file_problems = _comfyui.model_file_problems
else:

    def __getattr__(name: str) -> Any:
        if name in _COMFYUI_EXPORTS:
            module = importlib.import_module(_ADAPTERS["comfyui"])
            return getattr(module, _COMFYUI_EXPORTS[name])
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
