"""Build the final prompt.

Photo workflows: person + scene + reference roles + brand rules. Designed graphics
(social_creative) are built from the design system in a fixed order: the identity block first
(when the man is shown), then format and safe zones, layout, design, brand (colours and fonts
from brand.json, the brand guide's rules), text, reference roles. The identity, brand and text
sections are the fixed core; the rest varies with the format and the picks from the pools.

Reference images are numbered in the order adapters attach them: identity, then products,
then style. The logo is never sent or drawn: the prompt keeps the top-right corner clear and
the app pastes the real logo file there (workflows/logo.py).
"""

import re
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
        "IDENTITY: the same real person, the only person allowed in the image. Keep this exact "
        "person: same face, facial structure, hairline and hair, skin tone and age. Do not "
        "alter, beautify or blend their identity."
    ),
    "product": (
        "PRODUCT: include this exact product. Keep its shape, colours, materials, labels "
        "and printed text unchanged."
    ),
    "style": (
        "STYLE: copy only the look and layout (composition, colour grading, lighting mood, "
        "typography style, graphic elements). Ignore and never copy any person, face, hand, "
        "logo or wordmark in them, and do not copy their products, text or subject matter."
    ),
    "series": (
        "SERIES: slide 1 of this carousel. Match its scene, colours, text panel and decor so "
        "the slides look like one series; never copy the person or any face from it, and do "
        "not copy its text."
    ),
}
# Photo workflows do not load the design system; designs use core.sceneText instead.
SCENE_TEXT = (
    "No readable text in the scene: screens, phones, laptops, tablets, signs and papers show "
    "only abstract shapes, blurred interface blocks or simple icons, never letters, words or "
    "numbers."
)
PHOTO_PERSON = (
    "Person: the only person allowed in the image is the one in the identity reference images; "
    "nobody else appears. Any person, face or logo in other reference images is ignored."
)
LOGO_CORNER = (
    "Keep the top-right corner calm and free of important detail: the real logo is placed "
    "there afterwards. Do not draw any logo, wordmark or brand name."
)
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
    style: int = 0
    series: int = 0  # slide 1 of the same carousel, attached after the style images


def _image_range(start: int, count: int) -> str:
    return f"Image {start}" if count == 1 else f"Images {start}-{start + count - 1}"


def reference_lines(counts: RefCounts) -> list[str]:
    lines = []
    start = 1
    for role, count in (
        ("identity", counts.identity),
        ("product", counts.product),
        ("style", counts.style),
        ("series", counts.series),
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
    avoid = [rule for rule in brand.dont if _not_about_logo(rule)]
    if avoid:
        lines.append("- Avoid: " + " ".join(rule.rstrip(".") + "." for rule in avoid))
    return lines


def _not_about_logo(rule: str) -> bool:
    """brand.json rules on handling the logo itself: the model never draws it, so leave out."""
    return re.search(r"\bthe logo\b", rule, re.IGNORECASE) is None


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
    logo: bool = False,
) -> str:
    """Photo workflows (person_lifestyle, person_service).

    logo: the app pastes the logo afterwards, so the prompt keeps its corner calm.
    """
    sections = [_INTROS[spec.workflow_id]]
    if counts.identity:  # the identity block comes first
        sections.append(PHOTO_PERSON)
    if company is not None and company.name and service:
        sections.append(f"Company: {company.name}, {first_sentence(company.summary)}")
    if service:
        sections.append(f"Service: {service.strip()}")
    sections.append(f"Scene: {scene.strip()} {SCENE_TEXT}")

    refs = _reference_section(counts)
    if refs:
        sections.append(refs)

    text = "Text: do not add any text, captions, watermarks or logos."
    if logo:
        text += f" {LOGO_CORNER}"
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


_SLIDE_PLACES = {
    "hook": "the first slide",
    "tip": "a middle slide",
    "cta": "the last slide",
}


def _format_section(design: DesignChoice, system: DesignSystem, aspect_ratio: str) -> str:
    kind = system.kinds[design.kind]
    text = f"Create {kind.description}. Format: {aspect_ratio}."
    if design.slide_role is not None:  # never its number: no counts appear on a slide
        text += f" This is {_SLIDE_PLACES[design.slide_role]} of the carousel."
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
    if spec.family == "post":
        family = system.post_family
        block = family.stat if design.stat else family.points
        composition = family.composition if design.person else family.composition_no_person
        lines = [f"Post layout family: {composition}", spec.composition, block]
    else:
        lines = [f"Post format ({design.format}): {spec.composition}"]
    if design.slide_role is not None:
        slide = system.carousel.slides[design.slide_role]
        lines.append(f"Carousel slide ({_SLIDE_PLACES[design.slide_role]}): {slide}")
        lines.append(f"Carousel series: {system.carousel.series}")
        lines.append(f"Carousel navigation: {system.carousel.navigation}")
    if design.layout is not None:
        layout = system.layouts[design.layout]
        lines.append(f"Layout {design.layout} ({layout.use}): {layout.description}")
        if layout.split_poses:
            left, right = (system.pools.poses[pose].description for pose in layout.split_poses)
            lines.append(f"Poses: left half: {left}; right half: {right}.")
    if look.pose is not None:
        lines.append(f"Pose: {_sentence(look.pose.text)}")
    if not design.person:
        lines.append(f"People: {system.core.no_person}")
    if look.scene is not None:
        lines.append(f"Scene: {_sentence(look.scene.text)}")
    if details and details.strip():
        lines.append(f"Scene details: {details.strip()}")
    lines.append(f"Scene text: {system.core.scene_text}")
    if design.visual:
        name = "Tip icon" if design.slide_role == "tip" else "System visual"
        lines.append(f"{name}: {design.visual}")
    elif look.holograms is not None and not design.person:
        lines.append("System visual: the holograms described in the design.")
    if counts.product:
        lines.append("Product: feature the product shown in the product reference images.")
    return "\n".join(lines)


def heading_font(brand: BrandProfile | None) -> str:
    """The brand.json font used for headings (not the sub-heading or logo font)."""
    for font in brand.fonts if brand else []:
        usage = font.usage.lower()
        if "heading" in usage and "sub" not in usage:
            return font.name
    return "the brand heading font"


def body_font(brand: BrandProfile | None) -> str:
    """The one font for all supporting text: brand.json's body or sub-heading font."""
    for font in brand.fonts if brand else []:
        usage = font.usage.lower()
        if "body" in usage or ("sub" in usage and "heading" in usage):
            return font.name
    return "the brand body font"


def footer_text(company: CompanyProfile | None) -> str | None:
    """The handle, else the website without https:// (from services.md), for the footer."""
    if company is None:
        return None
    handle = company.fields.get("Handle", "").strip()
    if handle:
        return handle
    website = company.website.strip()
    for prefix in ("https://", "http://", "www."):
        website = website.removeprefix(prefix)
    return website.rstrip("/") or None


def _typography(
    design: DesignChoice, system: DesignSystem, brand: BrandProfile | None
) -> list[str]:
    spec = system.formats[design.format]
    defaults = system.typography
    font = system.core.heading_font.replace("{font}", heading_font(brand))
    body = system.core.body_font.replace("{font}", body_font(brand))
    lines = []
    if design.audience_line:
        lines.append(f"- Audience line typography: {system.core.audience_line} {font}")
    if design.headline:
        rule = spec.typography.get("headline", defaults.headline)
        if design.highlight:
            rule += f" {defaults.headline_highlight}"
        lines.append(f"- {_label(design, system, 'headline')} typography: {rule} {font}")
    if design.stat:
        rule = spec.typography.get("stat", defaults.stat)
        lines.append(f"- {_label(design, system, 'stat')} typography: {rule} {font}")
    if design.subheadline:
        rule = spec.typography.get("subheadline", defaults.subheadline)
        if design.sub_highlight:
            rule += f" {defaults.subheadline_highlight}"
        lines.append(f"- {_label(design, system, 'subheadline')} typography: {rule} {body}")
    if design.steps:
        rule = spec.typography.get("steps", defaults.steps)
        lines.append(f"- {_label(design, system, 'steps')} typography: {rule} {body}")
    if design.points:
        rule = spec.typography.get("points", defaults.points)
        lines.append(f"- Key point typography: {rule} {body}")
    if design.source_name:
        lines.append(f"- Source line typography: {system.core.source_line}")
    if design.chat or design.diagram or design.mini_checklist or design.before_after or design.cta:
        lines.append(f"- All other text (visual labels, button, footer): {body}")
    return lines


def _design_section(
    design: DesignChoice,
    look: DesignLook,
    system: DesignSystem,
    counts: RefCounts,
    brand: BrandProfile | None,
    footer: str | None,
    logo: bool,
) -> str:
    """Only what this format shows: the panel, holograms, decor and props are optional."""
    spec = system.formats[design.format]
    elements = system.elements
    lines = [f"- Canvas: {system.core.layout}"]
    if "textPanel" in spec.elements:
        lines.append(f"- Text panel: {elements.text_panel}")
    lines += _typography(design, system, brand)
    if design.chat:
        lines.append(f"- Chat example: {system.carousel.chat}")
    if design.diagram:
        lines.append(f"- Workflow diagram: {system.carousel.diagram}")
    if design.mini_checklist:
        lines.append(f"- Mini checklist: {system.carousel.checklist}")
    if design.before_after:
        lines.append(f"- Before / after: {system.carousel.before_after}")
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
    if logo:
        lines.append(f"- Logo corner: {system.core.logo}")
    if footer:
        story = bool(system.kinds[design.kind].safe_zone)
        safe = " Keep it just above the bottom safe zone." if story else ""
        lines.append(f"- Footer: {system.core.footer}{safe}")
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
        avoid = [rule for rule in brand.dont if _not_about_logo(rule)]
        if avoid:
            lines.append("- Avoid: " + " ".join(rule.rstrip(".") + "." for rule in avoid))
    rules = system.core.brand_rules
    typography = rules.typography.replace("{heading}", heading_font(brand)).replace(
        "{body}", body_font(brand)
    )
    lines += [
        f"- Colour rule: {rules.colours}",
        f"- Type rule: {typography}",
        f"- Spacing rule: {rules.spacing}",
    ]
    name = f" ({brand.brand_name})" if brand is not None else ""
    return f"Brand{name} guide, on every image: use only these colours and fonts.\n" + "\n".join(
        lines
    )


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
    "points": "Key point",
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
    if design.audience_line:
        items.append(f'- Audience line: "{design.audience_line.upper()}"')
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
    numbered = spec.numbered_points
    for number, point in enumerate(design.points, start=1):
        label = _label(design, system, "points")
        shown = f", numbered {number}" if numbered else ""
        items.append(f'- {label} {number}{shown}: "{point}"')
    for number, row in enumerate(design.mini_checklist, start=1):
        items.append(f'- Checklist row {number}: "{row}"')
    if design.before_after:
        before, after = design.before_after
        items += [f'- Before card: "{before}"', f'- After card: "{after}"']
    for number, (speaker, bubble) in enumerate(design.chat, start=1):
        items.append(f'- Chat bubble {number} ({speaker}): "{bubble}"')
    for number, step in enumerate(design.diagram, start=1):
        items.append(f'- Diagram step {number}: "{step}"')
    if design.cta:
        items.append(f'- {_label(design, system, "cta")}: "{design.cta}"')
    if design.icons:
        items.append(f"- {_label(design, system, 'icons')}: {_quoted(design.icons)}")
    if _is_split(design, system):
        items.append('- Symbol on the split button: "»"')
    if design.source_name:
        items.append(f'- Source line: "Source: {design.source_name}"')
    footer = footer_text(company)
    if footer:
        items.append(f'- Footer: "{footer}"')

    if items:
        only = rules.only.replace("{language}", text_language(brand))
        text = f"Text: {only}\n" + "\n".join(items) + f"\n{rules.nothing_else}"
    else:
        text = f"Text: {rules.none}"
    if not design.cta:
        text += f" {rules.no_button}"
    if look.holograms is not None:
        text += " " + rules.lettering.replace("{lettering}", '"AI" on the hologram chip or core')
    else:
        text += f" {rules.no_lettering}"
    if design.chat or design.diagram or design.mini_checklist or design.before_after:
        text += " The visual shows only its listed texts."
    if design.slide_role is not None:
        text += " No slide numbers, counters or page counts anywhere."
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
    logo: bool = True,
) -> str:
    """Designed graphics (social_creative): the format, the picked look and the fixed core.

    logo: the app pastes the logo afterwards, so the prompt keeps its corner empty.
    """
    sections = [
        # The identity block comes first, so the person is read before anything else.
        _identity_section(design, look, system, counts.identity) if design.person else None,
        _format_section(design, system, aspect_ratio),
        _layout_section(design, look, system, counts, details),
        _design_section(design, look, system, counts, brand, footer_text(company), logo),
        _brand_section(brand, system, company),
        _text_section(design, look, system, counts, brand, company),
        _reference_section(counts),
    ]
    return "\n\n".join(section for section in sections if section)


