"""Template adapter: no picture at all, for post formats (and carousel slides) without an image
slot. The app renders the whole design (workflows/text_overlay.py); nothing is sent anywhere
and it costs nothing. It returns a plain canvas the composer ignores.
"""

import io
import uuid

from PIL import Image

from content_automation.ai.image import (
    ASPECT_RATIOS,
    IMAGE_SIZES,
    GeneratedImage,
    ImageRequest,
    ImageResult,
    ProviderCapabilities,
)
from content_automation.core.config import Settings

_SIZES = {"1:1": (64, 64), "4:5": (64, 80), "9:16": (54, 96), "16:9": (96, 54)}


class TemplateImageProvider:
    name = "template"
    capabilities = ProviderCapabilities(
        max_identity_refs=0,
        max_object_refs=0,
        max_style_refs=0,
        max_total_refs=0,
        aspect_ratios=frozenset(ASPECT_RATIOS),
        image_sizes=frozenset(IMAGE_SIZES),
        est_cost_usd_per_image={size: 0.0 for size in IMAGE_SIZES},
        max_images_per_call=4,
        draws_text=False,
    )

    def generate(self, request: ImageRequest, model: str) -> ImageResult:
        buffer = io.BytesIO()
        Image.new("RGB", _SIZES[request.aspect_ratio], (0, 0, 0)).save(buffer, format="PNG")
        images = [GeneratedImage(data=buffer.getvalue(), mime_type="image/png")
                  for _ in range(request.count)]
        return ImageResult(images=images, provider=self.name, model=model,
                           provider_request_ids=[f"template-{uuid.uuid4().hex[:12]}"])


def create_provider(settings: Settings | None = None) -> TemplateImageProvider:
    return TemplateImageProvider()
