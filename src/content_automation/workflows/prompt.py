"""Build the final prompt: scene + reference roles + brand rules.

Reference images are numbered in the order adapters attach them:
identity, then objects (products, then logo), then style.
"""

from dataclasses import dataclass

from content_automation.references import BrandProfile
from content_automation.workflows.registry import WorkflowSpec

PHOTO_WORKFLOWS = frozenset({"person_lifestyle", "person_product"})

_INTROS = {
    "person_lifestyle": (
        "Create a photorealistic lifestyle photo of the person shown in the identity "
        "reference images."
    ),
    "person_product": (
        "Create a photorealistic photo of the person shown in the identity reference images, "
        "naturally using or presenting the product shown in the product reference images."
    ),
}
_VARIANT_INTROS = {
    "post": "Create a polished social media post image.",
    "ad": (
        "Create a social media advertisement image with one clear focal point "
        "and clean space for text."
    ),
    "carousel_slide": (
        "Create one slide of a social media carousel, designed to fit a consistent series."
    ),
}
_ROLES = {
    "identity": (
        "IDENTITY: the same real person. Keep this exact person: same face, facial features, "
        "skin tone, hair and build. Do not alter, beautify or blend their identity."
    ),
    "product": (
        "PRODUCT: include this exact product. Keep its shape, colours, materials, labels "
        "and printed text unchanged."
    ),
    "logo": (
        "BRAND LOGO: place this exact logo once, clearly visible and unaltered. "
        "Do not redraw or restyle it."
    ),
    "style": (
        "STYLE: copy only the look and layout (composition, colour grading, lighting mood, "
        "typography style, graphic elements). Do not copy their people, products, text "
        "or subject matter."
    ),
}


@dataclass(frozen=True)
class RefCounts:
    identity: int = 0
    product: int = 0
    logo: int = 0
    style: int = 0


def _image_range(start: int, count: int) -> str:
    return f"Image {start}" if count == 1 else f"Images {start}-{start + count - 1}"


def reference_lines(counts: RefCounts) -> list[str]:
    lines = []
    start = 1
    for role, count in (
        ("identity", counts.identity),
        ("product", counts.product),
        ("logo", counts.logo),
        ("style", counts.style),
    ):
        if count:
            lines.append(f"- {_image_range(start, count)} - {_ROLES[role]}")
            start += count
    return lines


def brand_lines(brand: BrandProfile, *, photo: bool) -> list[str]:
    lines = []
    if brand.tone:
        lines.append(f"- Tone: {brand.tone}")
    if brand.image_style:
        lines.append(f"- Image style: {brand.image_style}")
    if brand.colors:
        palette = ", ".join(f"{c.name} {c.hex}" for c in brand.colors)
        use = (
            "as subtle accents (clothing, props, background details)"
            if photo
            else "for backgrounds, shapes and text"
        )
        lines.append(f"- Brand colours, used {use}: {palette}")
    if brand.language:
        lines.append(f"- Any text in the image must be in {brand.language}.")
    if brand.dont:
        lines.append("- Avoid: " + " ".join(rule.rstrip(".") + "." for rule in brand.dont))
    return lines


def build_prompt(
    spec: WorkflowSpec,
    scene: str,
    counts: RefCounts,
    brand: BrandProfile | None,
    *,
    variant: str | None = None,
    headline: str | None = None,
) -> str:
    photo = spec.workflow_id in PHOTO_WORKFLOWS
    if photo:
        intro = _INTROS[spec.workflow_id]
    else:
        intro = _VARIANT_INTROS[variant or spec.default_variant or "post"]
        if counts.identity:
            intro += " Feature the person shown in the identity reference images."
        if counts.product:
            intro += " Feature the product shown in the product reference images."
    sections = [intro, f"Scene: {scene.strip()}"]

    refs = reference_lines(counts)
    if refs:
        sections.append("Reference images (numbered in the order attached):\n" + "\n".join(refs))

    if headline:
        sections.append(
            f'Text: render this headline exactly, spelled correctly and clearly legible: '
            f'"{headline.strip()}"'
        )
    elif photo:
        sections.append("Text: do not add any text, captions, watermarks or logos.")
    else:
        sections.append("Text: only add text if the scene asks for it, and spell it exactly.")

    if brand is not None:
        rules = brand_lines(brand, photo=photo)
        if rules:
            sections.append(f"Brand guidelines ({brand.brand_name}):\n" + "\n".join(rules))
    return "\n\n".join(sections)
