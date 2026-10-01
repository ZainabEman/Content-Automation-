"""Offline mock adapter: placeholder PNGs that show the prompt.

IMAGE_MODEL=mock-fail raises a provider error, IMAGE_MODEL=mock-timeout raises a
timeout, and any other model succeeds. Images are always drawn at 1K size.
Its limits are those of gemini-3.1-flash-image (the model behind OpenRouter).
"""

import io
import textwrap
import uuid

from PIL import Image, ImageDraw, ImageFont

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

_SIZES_1K = {"1:1": (1024, 1024), "4:5": (819, 1024), "9:16": (576, 1024), "16:9": (1024, 576)}
_BACKGROUNDS = ((226, 232, 240), (254, 243, 199), (220, 252, 231), (237, 233, 254))


class MockImageProvider:
    name = "mock"
    capabilities = ProviderCapabilities(
        max_identity_refs=4,
        max_object_refs=10,
        max_style_refs=3,
        max_object_and_style_refs=10,
        aspect_ratios=frozenset(ASPECT_RATIOS),
        image_sizes=frozenset(IMAGE_SIZES),
        est_cost_usd_per_image={size: 0.0 for size in IMAGE_SIZES},
        max_images_per_call=4,
    )

    def generate(self, request: ImageRequest, model: str) -> ImageResult:
        if model == "mock-fail":
            raise ImageProviderError("Mock provider failure (IMAGE_MODEL=mock-fail).")
        if model == "mock-timeout":
            raise ImageTimeoutError("Mock provider timeout (IMAGE_MODEL=mock-timeout).")
        images = [
            GeneratedImage(data=_render(request, index), mime_type="image/png")
            for index in range(1, request.count + 1)
        ]
        return ImageResult(
            images=images,
            provider=self.name,
            model=model,
            provider_request_ids=[f"mock-{uuid.uuid4().hex[:12]}"],
        )


def _render(request: ImageRequest, index: int) -> bytes:
    width, height = _SIZES_1K[request.aspect_ratio]
    image = Image.new("RGB", (width, height), _BACKGROUNDS[(index - 1) % len(_BACKGROUNDS)])
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.load_default(size=40)
    body_font = ImageFont.load_default(size=28)
    draw.rectangle((8, 8, width - 9, height - 9), outline=(71, 85, 105), width=4)
    draw.text((40, 40), f"MOCK {index}/{request.count}", fill=(15, 23, 42), font=title_font)
    refs = (
        f"refs: {len(request.identity_refs)} identity, {len(request.object_refs)} object, "
        f"{len(request.style_refs)} style"
    )
    draw.text((40, 96), f"{request.aspect_ratio} · {request.image_size}", fill=(51, 65, 85),
              font=body_font)
    draw.text((40, 136), refs, fill=(51, 65, 85), font=body_font)
    wrap_width = max(20, width // 17)
    lines = textwrap.wrap(request.prompt, wrap_width)[: (height - 240) // 36]
    draw.multiline_text((40, 200), "\n".join(lines), fill=(15, 23, 42), font=body_font, spacing=8)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def create_provider(settings: Settings | None = None) -> MockImageProvider:
    return MockImageProvider()
