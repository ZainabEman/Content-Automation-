"""Build the final prompt.

Photo workflows: scene + reference roles + brand rules. Designed graphics (social_creative)
are built from the design system in a fixed order: format and safe zones, layout, design,
brand (colours, fonts, logo from brand.json), identity, text, reference roles. The brand,
identity and text sections are the fixed core; the rest varies with the format and the
picks from the pools.

Reference images are numbered in the order adapters attach them:
identity, then objects (products, then logo), then style.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from content_automation.references import (
    BrandColor,
    BrandProfile,
    CompanyProfile,
    first_sentence,
)
from content_automation.workflows.design_system import (
    COLOR_ROLES,
    ColorRole,
    DesignChoice,
    DesignSystem,
    TextField,
)
from content_automation.workflows.registry import WorkflowSpec
from content_automation.workflows.variety import DesignLook

DEFAULT_TEXT_LANGUAGE = "English"
_LANGUAGE_NAMES = {"en": "English"}

_INTROS = {
    "person_lifestyle": (
        "Create a photorealistic lifestyle photo of the person shown in the identity "
        "reference images."
    ),
    "person_service": (
        "Create a photorealistic photo of the person shown in the identity reference images, "
        "at work providing or presenting the service described below."
    ),
}
_ROLES = {
    "identity": (
        "IDENTITY: the same real person. Keep this exact person: same face, facial structure, "
        "hairline and hair, skin tone and age. Do not alter, beautify or blend their identity."
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
        "typography style, graphic elements). Never copy any person or face from them, and "
        "do not copy their products, text or subject matter."
    ),
}
_ROLE_LABELS: dict[ColorRole, str] = {
    "background": "Background colour",
    "accent": "Accent / glow colour",
    "highlight": "Highlight colour",
    "text": "Text colour",
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


def _reference_section(counts: RefCounts) -> str | None:
    refs = reference_lines(counts)
    if not refs:
        return None
    return "Reference images (numbered in the order attached):\n" + "\n".join(refs)


def brand_lines(brand: BrandProfile) -> list[str]:
    lines = []
    if brand.tone:
        lines.append(f"- Tone: {brand.tone}")
    if brand.image_style:
        lines.append(f"- Image style: {brand.image_style}")
    if brand.colors:
        palette = ", ".join(f"{c.name} {c.hex}" for c in brand.colors)
        lines.append(
            "- Brand colours, used as subtle accents (clothing, props, background details): "
            f"{palette}"
        )
    if brand.dont:
        lines.append("- Avoid: " + " ".join(rule.rstrip(".") + "." for rule in brand.dont))
    return lines


def text_language(brand: BrandProfile | None) -> str:
    """On-image text language: brand.json "language" (e.g. "en"), default English."""
    code = brand.language.strip() if brand else ""
    return _LANGUAGE_NAMES.get(code.lower(), code) or DEFAULT_TEXT_LANGUAGE


def build_prompt(
    spec: WorkflowSpec,
    scene: str,
    counts: RefCounts,
    brand: BrandProfile | None,
    *,
    service: str | None = None,
    company: CompanyProfile | None = None,
) -> str:
    """Photo workflows (person_lifestyle, person_service)."""
    sections = [_INTROS[spec.workflow_id]]
    if company is not None and company.name and service:
        sections.append(f"Company: {company.name}, {first_sentence(company.summary)}")
    if service:
        sections.append(f"Service: {service.strip()}")
    sections.append(f"Scene: {scene.strip()}")

    refs = _reference_section(counts)
    if refs:
        sections.append(refs)

    text = "Text: do not add any text, captions, watermarks or logos."
    text += f" Any text in the image must be in {text_language(brand)}."
    if company is not None and company.content_rules:
        text += f" Content rules: {company.content_rules}"
    sections.append(text)

    if brand is not None:
        rules = brand_lines(brand)
        if rules:
            sections.append(f"Brand guidelines ({brand.brand_name}):\n" + "\n".join(rules))
    return "\n\n".join(sections)


def _luminance(color: BrandColor) -> float:
    red, green, blue = (int(color.hex[start : start + 2], 16) for start in (1, 3, 5))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def role_colors(brand: BrandProfile, system: DesignSystem) -> dict[ColorRole, BrandColor]:
    """Map the design's colour roles to brand.json colours by their "usage" text.

    Without a match the background is the darkest brand colour and the text the lightest.
    """
    found: dict[ColorRole, BrandColor] = {}
    for role in COLOR_ROLES:
        words = [word.lower() for word in system.core.color_roles[role].usage]
        for color in brand.colors:
            if any(word in color.usage.lower() for word in words):
                found[role] = color
                break
    by_lightness = sorted(brand.colors, key=_luminance)
    found.setdefault("background", by_lightness[0])
    if by_lightness[-1] is not found["background"]:
        found.setdefault("text", by_lightness[-1])
    return found


def _sentence(text: str) -> str:
    """A pool description as a sentence: capital first letter, one full stop."""
    text = text.strip().rstrip(".")
    return f"{text[:1].upper()}{text[1:]}."


def _format_section(design: DesignChoice, system: DesignSystem, aspect_ratio: str) -> str:
    kind = system.kinds[design.kind]
    text = f"Create {kind.description}. Format: {aspect_ratio}."
    if design.slide is not None:
        text += f" This is slide {design.slide[0]} of {design.slide[1]}."
    if kind.safe_zone:
        text += f" Safe zones: {kind.safe_zone}"
    return text


def _layout_section(
    design: DesignChoice,
    look: DesignLook,
    system: DesignSystem,
    counts: RefCounts,
    details: str | None,
) -> str:
    spec = system.formats[design.format]
    lines = [f"Post format ({design.format}): {spec.composition}"]
    if design.slide_role is not None:
        slide = system.carousel.slides[design.slide_role]
        lines.append(f"Carousel {design.slide_role} slide: {slide}")
        lines.append(f"Carousel navigation: {system.carousel.navigation}")
    if design.layout is not None:
        layout = system.layouts[design.layout]
        lines.append(f"Layout {design.layout} ({layout.use}): {layout.description}")
        if layout.split_poses:
            left, right = (system.pools.poses[pose].description for pose in layout.split_poses)
            lines.append(f"Poses: left half: {left}; right half: {right}.")
    if look.pose is not None:
        lines.append(f"Pose: {_sentence(look.pose.text)}")
    if look.scene is not None:
        lines.append(f"Scene: {_sentence(look.scene.text)}")
    if details and details.strip():
        lines.append(f"Scene details: {details.strip()}")
    if design.visual:
        name = "Tip icon" if design.slide_role == "tip" else "System visual"
        lines.append(f"{name}: {design.visual}")
    elif look.holograms is not None and not design.person:
        lines.append("System visual: the holograms described in the design.")
    if counts.product:
        lines.append("Product: feature the product shown in the product reference images.")
    return "\n".join(lines)


def _typography(design: DesignChoice, system: DesignSystem) -> list[str]:
    spec = system.formats[design.format]
    defaults = system.typography
    lines = []
    if design.headline:
        rule = spec.typography.get("headline", defaults.headline)
        if design.highlight:
            rule += f" {defaults.headline_highlight}"
        lines.append(f"- {_label(design, system, 'headline')} typography: {rule}")
    if design.stat:
        rule = spec.typography.get("stat", defaults.stat)
        lines.append(f"- {_label(design, system, 'stat')} typography: {rule}")
    if design.subheadline:
        rule = spec.typography.get("subheadline", defaults.subheadline)
        if design.sub_highlight:
            rule += f" {defaults.subheadline_highlight}"
        lines.append(f"- {_label(design, system, 'subheadline')} typography: {rule}")
    if design.steps:
        rule = spec.typography.get("steps", defaults.steps)
        lines.append(f"- {_label(design, system, 'steps')} typography: {rule}")
    return lines


def _design_section(
    design: DesignChoice, look: DesignLook, system: DesignSystem, counts: RefCounts
) -> str:
    """Only what this format shows: the panel, holograms, decor and props are optional."""
    spec = system.formats[design.format]
    elements = system.elements
    lines = []
    if "textPanel" in spec.elements:
        lines.append(f"- Text panel: {elements.text_panel}")
    lines += _typography(design, system)
    if design.cta and design.cta_icon:
        button = elements.cta_button
        icon = button.icons[design.cta_icon].icon
        cta = f"- CTA button: {button.description} Icon: {icon}. {button.pointer}"
        lines.append(cta.rstrip())
    if look.holograms is not None:
        holograms = f"- Holograms: {_sentence(look.holograms.text)}"
        if design.person and elements.holograms_person:
            holograms += f" {elements.holograms_person}"
        lines.append(holograms)
    if design.icons:
        lines.append(f"- Icon row: {elements.icon_row}")
    if look.decor is not None:
        lines.append(f"- Decor: {_sentence(look.decor.text)}")
    if look.props is not None:
        lines.append(f"- Props: {_sentence(look.props.text)}")
    if counts.logo:
        lines.append(f"- Logo: {system.core.logo}")
    return "Design (follow it closely):\n" + "\n".join(lines)


def _brand_section(
    brand: BrandProfile | None, system: DesignSystem, company: CompanyProfile | None
) -> str | None:
    lines = []
    if company is not None and company.name:
        lines.append(f"- Company: {company.name}, {first_sentence(company.summary)}")
    if brand is not None:
        if brand.tone:
            lines.append(f"- Tone: {brand.tone}")
        colors = role_colors(brand, system)
        for role in COLOR_ROLES:
            if role in colors:
                color = colors[role]
                lines.append(
                    f"- {_ROLE_LABELS[role]}: {color.name} {color.hex}, for "
                    f"{system.core.color_roles[role].use}"
                )
        others = [c for c in brand.colors if all(c is not used for used in colors.values())]
        if others:
            lines.append(
                "- Other brand colours, for small details only: "
                + ", ".join(f"{c.name} {c.hex}" for c in others)
            )
        if brand.fonts:
            fonts = [f"{f.name} ({f.usage})" if f.usage else f.name for f in brand.fonts]
            lines.append(f"- Fonts: {'; '.join(fonts)}. {system.core.fonts}")
        if brand.logo_rules:
            lines.append(f"- Logo: {brand.logo_rules[0]}")
        if brand.dont:
            lines.append("- Avoid: " + " ".join(rule.rstrip(".") + "." for rule in brand.dont))
    if not lines:
        return None
    name = f" ({brand.brand_name})" if brand is not None else ""
    return f"Brand{name}: use only these colours and fonts.\n" + "\n".join(lines)


def _is_split(design: DesignChoice, system: DesignSystem) -> bool:
    return design.layout is not None and bool(system.layouts[design.layout].split_poses)


def _identity_section(
    design: DesignChoice, look: DesignLook, system: DesignSystem, count: int
) -> str:
    """The face comes from the photos only; nothing here describes his features."""
    identity = system.core.identity
    images = (
        "identity reference image 1" if count == 1 else f"identity reference images 1–{count}"
    )
    text = "Person: " + " ".join(identity.rules).replace("{images}", images)
    if look.wardrobe is not None:
        text += f" Wardrobe: {_sentence(look.wardrobe.text)}"
    if _is_split(design, system):
        text += f" {identity.split}"
    return text


def _quoted(items: Iterable[str]) -> str:
    return ", ".join(f'"{item}"' for item in items)


_TEXT_LABELS: dict[TextField, str] = {
    "headline": "Headline",
    "subheadline": "Subheadline",
    "cta": "CTA button label",
    "icons": "Icon row labels, one under each icon",
    "stat": "Big number",
    "steps": "Step",
}


def _label(design: DesignChoice, system: DesignSystem, field: TextField) -> str:
    return system.formats[design.format].labels.get(field) or _TEXT_LABELS[field]


def _text_section(
    design: DesignChoice,
    look: DesignLook,
    system: DesignSystem,
    counts: RefCounts,
    brand: BrandProfile | None,
    company: CompanyProfile | None,
) -> str:
    spec = system.formats[design.format]
    rules = system.core.text
    items = []
    if design.headline:
        caps = spec.headline_caps
        line = f'- {_label(design, system, "headline")}: '
        line += f'"{design.headline.upper() if caps else design.headline}"'
        if design.highlight:
            words = _quoted(word.upper() if caps else word for word in design.highlight)
            line += f" (in the highlight colour: {words})"
        items.append(line)
    if design.stat:
        items.append(f'- {_label(design, system, "stat")}: "{design.stat}"')
    if design.subheadline:
        items += [f'- {name}: "{fixed}"' for name, fixed in spec.fixed_texts.items()]
        line = f'- {_label(design, system, "subheadline")}: "{design.subheadline}"'
        if design.sub_highlight:
            line += f' (in the highlight colour: "{design.sub_highlight}")'
        items.append(line)
    for number, step in enumerate(design.steps, start=1):
        items.append(f'- {_label(design, system, "steps")} {number}, numbered {number}: "{step}"')
    if design.cta:
        items.append(f'- {_label(design, system, "cta")}: "{design.cta}"')
    if design.icons:
        items.append(f"- {_label(design, system, 'icons')}: {_quoted(design.icons)}")
    if design.slide is not None:
        number, total = design.slide
        items.append(f'- Slide number, next to the slide dots: "{number}/{total}"')
    if _is_split(design, system):
        items.append('- Symbol on the split button: "»"')

    if items:
        only = rules.only.replace("{language}", text_language(brand))
        text = f"Text: {only}\n" + "\n".join(items) + f"\n{rules.nothing_else}"
    else:
        text = f"Text: {rules.none}"
    if not design.cta:
        text += f" {rules.no_button}"
    lettering = ["the logo"] if counts.logo else []
    if look.holograms is not None:
        lettering.append('"AI" on the hologram chip or core')
    if lettering:
        text += " " + rules.lettering.replace("{lettering}", " and ".join(lettering))
    if company is not None and company.content_rules:
        text += f" Content rules: {company.content_rules}"
    return text


def build_design_prompt(
    design: DesignChoice,
    look: DesignLook,
    system: DesignSystem,
    counts: RefCounts,
    brand: BrandProfile | None,
    *,
    aspect_ratio: str,
    details: str | None = None,
    company: CompanyProfile | None = None,
) -> str:
    """Designed graphics (social_creative): the format, the picked look and the fixed core."""
    sections = [
        _format_section(design, system, aspect_ratio),
        _layout_section(design, look, system, counts, details),
        _design_section(design, look, system, counts),
        _brand_section(brand, system, company),
        _identity_section(design, look, system, counts.identity) if design.person else None,
        _text_section(design, look, system, counts, brand, company),
        _reference_section(counts),
    ]
    return "\n\n".join(section for section in sections if section)


