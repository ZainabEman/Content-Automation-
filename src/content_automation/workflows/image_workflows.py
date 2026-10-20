"""Named image workflows: check inputs, pick references, build the prompt, run the job."""

import json
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

from content_automation.ai.image import (
    ASPECT_RATIOS,
    MAX_COUNT,
    AspectRatio,
    ImageRequest,
    ProviderCapabilities,
    ReferenceImage,
    get_provider,
)
from content_automation.content.design_variation import Variation, can_mirror
from content_automation.content.design_variation import apply as apply_variation
from content_automation.content.designer_prompt import (
    DesignerInputs,
    DesignerPromptError,
    default_mode,
    designer_inputs,
    mirror_words,
)
from content_automation.content.directions import (
    CANVAS,
    Direction,
    DirectionCatalog,
    DirectionError,
    Layout,
    load_directions,
)
from content_automation.content.formats import (
    FormatError,
    PostFormat,
    image_prompt,
    load_formats,
)
from content_automation.content.roman_prompt import (
    AI_DISCLOSURE,
    Combination,
    RomanPromptError,
    character_token,
    parse_combination,
    pick_combination,
)
from content_automation.content.roman_prompt import build_prompt as roman_prompt_text
from content_automation.content.routing import RoutingError, check_route
from content_automation.core.config import Settings
from content_automation.core.jobs import DETAILS_FILE, Job, JobReference
from content_automation.references import (
    BrandProfile,
    ReferenceLibraryError,
    brand_path,
    load_brand,
    load_company,
    load_set,
    select_identity_refs,
    select_logo_ref,
    select_rotating_style_refs,
    select_set_refs,
    select_style_refs,
)
from content_automation.research.store import find_article, number_in_article
from content_automation.workflows.design_render import DesignRenderError, logo_file
from content_automation.workflows.design_system import (
    DEFAULT_FORMAT,
    MAX_SOURCE_WORDS,
    DesignChoice,
    DesignSystem,
    load_design_system,
    resolve_design,
)
from content_automation.workflows.direction_job import (
    DESIGNER_CHECK_FAILED,
    DirectionDesign,
    DirectionJobError,
    direction_layout,
    direction_settings,
    has_picture,
    illustration_prompt,
    picture_aspect,
)
from content_automation.workflows.image_job import job_references, raw_image, run_image_job
from content_automation.workflows.logo import LogoError, LogoOverlay, check_logo
from content_automation.workflows.prompt import RefCounts, build_design_prompt, build_prompt
from content_automation.workflows.registry import (
    DEFAULT_STYLE_COUNT,
    INPUT_FLAGS,
    InputName,
    WorkflowError,
    WorkflowSpec,
    get_workflow,
)
from content_automation.workflows.start_images import StartImageError, resolve_start_image
from content_automation.workflows.text_overlay import (
    TextOverlay,
    format_overlay,
    prepare_text_overlay,
    use_text_overlay,
)
from content_automation.workflows.text_reader import estimated_check_usd, text_check_config
from content_automation.workflows.variety import (
    DesignLook,
    DesignPicks,
    choose_layout,
    choose_look,
    flatten,
    recent_packages,
)

AD_VARIANTS = 3  # ads are made as 3 variants unless a count is given
MAX_REFERENCE_IMAGES = 14  # the image model's limit for all reference images together
PERSON_STYLE_REFS = 1  # an image with the man gets at most one (people- and logo-free) example
# --variant is the old name of --kind.
KIND_BY_VARIANT = {"post": "organic", "ad": "ad", "carousel_slide": "carousel_slide"}


@dataclass
class WorkflowInputs:
    prompt: str = ""  # photo workflows: the scene; designs: the scene, or extra scene details
    identity_set: str | None = None
    product_set: str | None = None
    style_set: str | None = None
    style_count: int | None = None
    variant: str | None = None
    headline: str | None = None
    logo: bool = False
    aspect_ratio: str | None = None
    count: int = 1
    request: str | None = None
    service: str | None = None
    # Designed graphics (social_creative); checked by resolve_design().
    format: str | None = None
    kind: str | None = None
    layout: str | None = None
    pose: str | None = None
    highlight: str | None = None  # comma-separated headline words
    subheadline: str | None = None
    sub_highlight: str | None = None
    cta: str | None = None
    cta_icon: str | None = None
    icons: str | None = None  # comma-separated labels
    visual: str | None = None
    stat: str | None = None
    source: str | None = None  # research article ID behind a stat or news line
    source_name: str | None = None  # stat: the publisher for "Source: ..." (default: article's)
    steps: str | None = None  # "|"-separated
    audience_line: str | None = None  # "FOR DENTAL PRACTICES"
    chat: str | None = None  # tip slides: "Customer: ...|Bot: ..."
    diagram: str | None = None  # tip slides: "Step one|Step two|Step three"
    points: str | None = None  # posts: 3 key points "One|Two|Three"
    mini_checklist: str | None = None  # tip slides: 3 rows "One|Two|Three"
    before_after: str | None = None  # tip slides: "Before|After"
    slide: str | None = None  # "N/TOTAL"
    slide_role: str | None = None
    no_person: bool = False  # post formats only: leave the man out (a LinkedIn post)
    card: str | None = None  # live fix: JSON of the person-post card (platform, tag, icons, ...)
    # Variable parts: a pool ID from the design system or own words; picked when left out.
    scene: str | None = None
    wardrobe: str | None = None
    props: str | None = None
    # The person to show when the design has one and no identity_set is given (from a brief);
    # unlike identity_set it is simply unused by designs without a person.
    fallback_identity_set: str | None = None
    # Carousel slides 2+: slide 1's image ("<jobId>/image-1.png"), attached as a style image.
    first_slide: str | None = None
    # Topic and audience, to pick a relevant scene (default: the request and the texts).
    context: str | None = None
    # Picks to avoid, newest first (from a brief's package); default: the newest packages.
    history: list[DesignPicks] | None = None
    # A post format (config/post_formats.json): its ID, the copy as JSON, the carousel slide
    # type (cover, body, final) and the topic; the format's prompt and zones replace the design.
    post_format: str | None = None
    format_copy: str | None = None
    slide_type: str | None = None
    topic: str | None = None
    # Phase D: a design direction (config/design_directions.json) instead of a post format;
    # format_copy holds its copy, slide_type the carousel slide role, topic seeds the layout.
    direction: str | None = None
    direction_platform: str | None = None
    # v5 R6.3: set at planning time (package.json requiresRoman); None = the variant decides
    requires_roman: bool | None = None
    # 2026-10-20: Roman's combination (side/background/pose/hologram), chosen at stage 1
    roman_combination: str | None = None
    # v6 (R3.4/R3.5): designer | composite (None: config/designer_prompts.json mode), the
    # designer attempt (2 = the automatic retry), and the package's variation
    design_mode: str | None = None
    design_attempt: int = 1
    variation: str | None = None

    def provided(self) -> set[InputName]:
        values: dict[InputName, str | bool | None] = {
            "identity_set": self.identity_set,
            "product_set": self.product_set,
            "style_set": self.style_set,
            "variant": self.variant,
            "headline": self.headline,
            "logo": self.logo,
            "service": (self.service or "").strip() or None,
            "format": self.format,
            "kind": self.kind,
            "layout": self.layout,
            "pose": self.pose,
            "highlight": self.highlight,
            "subheadline": self.subheadline,
            "sub_highlight": self.sub_highlight,
            "cta": self.cta,
            "cta_icon": self.cta_icon,
            "icons": self.icons,
            "visual": self.visual,
            "stat": self.stat,
            "source": self.source,
            "source_name": self.source_name,
            "steps": self.steps,
            "slide": self.slide,
            "slide_role": self.slide_role,
            "scene": self.scene,
            "wardrobe": self.wardrobe,
            "props": self.props,
            "first_slide": self.first_slide,
            "audience_line": self.audience_line,
            "chat": self.chat,
            "diagram": self.diagram,
            "points": self.points,
            "mini_checklist": self.mini_checklist,
            "before_after": self.before_after,
        }
        return {name for name, value in values.items() if value not in (None, "", False)}


@dataclass
class PreparedWorkflow:
    spec: WorkflowSpec
    request: ImageRequest
    product_refs: list[ReferenceImage] = field(default_factory=list)
    logo: LogoOverlay | None = None  # pasted by the app after generation; never sent
    text: TextOverlay | None = None  # rendered by the app before the logo (no-text providers)
    references: list[JobReference] = field(default_factory=list)  # in the order attached
    inputs: dict[str, str | bool] = field(default_factory=dict)
    picks: DesignPicks | None = None  # designs: what was used from the pools
    person_shown: bool = False  # the result needs the person check before it is used
    settings: Settings | None = None  # a post format: its own provider (never swapped)
    design: DirectionDesign | None = None  # Phase D: the app draws the direction after it

    @property
    def product_asset_ids(self) -> list[str]:
        return [ref.asset_id for ref in self.product_refs]

    @property
    def brand_asset_ids(self) -> list[str]:
        return [self.logo.asset_id] if self.logo is not None else []


def _check_inputs(spec: WorkflowSpec, inputs: WorkflowInputs) -> None:
    given = inputs.provided()
    allowed = set(spec.required_inputs) | set(spec.optional_inputs)
    unused = sorted(INPUT_FLAGS[name] for name in given - allowed)
    if unused:
        raise WorkflowError(f"{spec.workflow_id} does not use {', '.join(unused)}.")
    missing = [INPUT_FLAGS[name] for name in spec.required_inputs if name not in given]
    if missing:
        raise WorkflowError(f"{spec.workflow_id} needs {', '.join(missing)}.")
    if not spec.designed and not inputs.prompt.strip():
        raise WorkflowError("--prompt cannot be empty.")
    if inputs.variant is not None and inputs.variant not in spec.variants:
        raise WorkflowError(f"--variant must be one of: {', '.join(spec.variants)}.")
    if inputs.aspect_ratio is not None and inputs.aspect_ratio not in ASPECT_RATIOS:
        raise WorkflowError(f"--aspect must be one of: {', '.join(ASPECT_RATIOS)}.")
    if not 1 <= inputs.count <= MAX_COUNT:
        raise WorkflowError(f"--count must be between 1 and {MAX_COUNT}.")
    if inputs.style_count is not None:
        if "style_set" not in allowed:
            raise WorkflowError(f"{spec.workflow_id} does not use --style-count.")
        if inputs.style_count < 1:
            raise WorkflowError("--style-count must be at least 1.")


def _load_brand_if_present(settings: Settings) -> BrandProfile | None:
    if not brand_path(settings.references_dir).is_file():
        return None
    return load_brand(settings.references_dir)


def _design_identity_set(
    design: DesignChoice, inputs: WorkflowInputs, settings: Settings
) -> str | None:
    """A design that shows the person always gets identity photos; the others get none."""
    if design.person:
        return (
            inputs.identity_set or inputs.fallback_identity_set or settings.default_identity_set
        )
    if inputs.identity_set:
        raise WorkflowError(
            f"{design.label} shows no person: remove --set, or pick a layout or format "
            "that shows him."
        )
    return None


def _identity_refs(
    set_id: str, max_n: int, design: DesignChoice | None, settings: Settings
) -> list[ReferenceImage]:
    problem = f"Identity set {set_id} has no usable photos."
    try:
        refs = select_identity_refs(set_id, max_n, settings.references_dir)
        if refs:
            return refs
    except ReferenceLibraryError as error:
        if design is None:
            raise
        problem = str(error)
    if design is None:
        raise WorkflowError(problem)
    raise WorkflowError(
        f"{design.label} shows the person, so identity photos are required, but: {problem} "
        "Add his photos, run `uv run ca refs scan`, then pass --set or set "
        "DEFAULT_IDENTITY_SET in .env."
    )


def _design_aspect(design: DesignChoice, system: DesignSystem, wanted: str | None) -> str:
    allowed = system.kinds[design.kind].aspects
    if wanted is None:
        return allowed[0]
    if wanted not in allowed:
        raise WorkflowError(
            f"--aspect for --kind {design.kind} must be one of: {', '.join(allowed)}."
        )
    return wanted


def _check_source(design: DesignChoice, settings: Settings) -> DesignChoice:
    """A stat is refused unless its number is written in the research article it names.

    A stat also shows "Source: <publisher>": the given --source-name must be the article's
    publisher (its source or web address); without one, the article's source is used.
    """
    if design.source is None:
        return design
    article = find_article(settings.research_dir, design.source)
    if article is None:
        raise WorkflowError(
            f"--source {design.source} is not a saved research article (see research.md or "
            "`uv run ca research digest` for the IDs)."
        )
    if design.stat is not None and not number_in_article(design.stat, article):
        raise WorkflowError(
            f'Refused: the number "{design.stat}" is not in research article {design.source} '
            f'("{article.title}"). A stat must come from the research; never invent one.'
        )
    if design.format != "stat":
        return design
    publisher = f"{article.source} {article.url}".casefold()
    if design.source_name is not None:
        if design.source_name.casefold().replace(" ", "") not in publisher.replace(" ", ""):
            raise WorkflowError(
                f'--source-name "{design.source_name}" is not the publisher of research article '
                f'{design.source} ("{article.source}"); use a short form of that name.'
            )
        return design
    name = " ".join(article.source.split("(")[0].split()[:MAX_SOURCE_WORDS]) or article.source
    return replace(design, source_name=name)


def _first_slide_ref(design: DesignChoice, inputs: WorkflowInputs, settings: Settings) -> (
    ReferenceImage | None
):
    """Slide 1's image for the later slides of a carousel: same scene, colours and decor.

    The logo-free original is attached (the model must not copy a logo), and a slide 1 that
    failed the person check is never used.
    """
    if not inputs.first_slide:
        return None
    if design.format != "carousel" or design.slide_role == "hook":
        raise WorkflowError("--first-slide is for carousel slides after the first.")
    try:
        found = resolve_start_image(inputs.first_slide, settings)
    except StartImageError as error:
        raise WorkflowError(f"--first-slide: {error}") from None
    folder, name = found.path.parent, found.path.name
    try:
        review = Job.load(folder / DETAILS_FILE).review(name)
    except (OSError, ValueError):
        review = None
    if review is not None and review.result == "fail":
        raise WorkflowError(
            f"--first-slide {inputs.first_slide} failed the person check; regenerate slide 1 "
            "first. A failed slide 1 is never used for later slides."
        )
    raw = raw_image(folder, name)
    if raw is None:  # made before the app pasted logos
        return ReferenceImage(asset_id=found.asset_id, path=found.path, source=found.source)
    source = f"{found.source.removesuffix(name)}raw/{name}"
    return ReferenceImage(asset_id=found.asset_id, path=raw, source=source)


def _logo(settings: Settings, brand: BrandProfile | None) -> LogoOverlay:
    """The logo the app pastes on; checked now, so a bad file stops before any cost."""
    try:
        ref = select_logo_ref(settings.references_dir, preferred=brand.logo_file if brand else None)
        overlay = LogoOverlay(path=ref.path, source=ref.source, asset_id=ref.asset_id)
        check_logo(overlay)
    except (ReferenceLibraryError, LogoError) as error:
        raise WorkflowError(str(error)) from None
    return overlay


def _context(inputs: WorkflowInputs) -> str:
    """What the post is about, for picking a relevant scene."""
    parts = [
        inputs.request, inputs.audience_line, inputs.headline, inputs.subheadline, inputs.prompt
    ]
    return " ".join(part for part in parts if part)


def _variety_seed(design: DesignChoice) -> str:
    """Picks follow the content, so different posts differ; carousel slides share one look."""
    if design.format == "carousel":
        return f"carousel|{design.slide[1] if design.slide else ''}"
    texts = [design.headline, design.subheadline, design.stat, *design.steps]
    return "|".join([design.format, *(text or "" for text in texts)])


def _recorded_design(design: DesignChoice, look: DesignLook) -> dict[str, str | bool]:
    values = {
        "format": design.format,
        "kind": design.kind,
        "layout": design.layout,
        "highlight": ", ".join(design.highlight),
        "subheadline": design.subheadline,
        "subHighlight": design.sub_highlight,
        "cta": design.cta,
        "ctaIcon": design.cta_icon,
        "icons": ", ".join(design.icons),
        "visual": design.visual,
        "stat": design.stat,
        "source": design.source,
        "steps": " | ".join(design.steps),
        "audienceLine": design.audience_line,
        "chat": " | ".join(f"{speaker}: {text}" for speaker, text in design.chat),
        "diagram": " | ".join(design.diagram),
        "points": " | ".join(design.points),
        "miniChecklist": " | ".join(design.mini_checklist),
        "beforeAfter": " | ".join(design.before_after),
        "slide": "/".join(str(part) for part in design.slide) if design.slide else None,
        "slideRole": design.slide_role,
        **look.ids(),
    }
    return {name: value for name, value in values.items() if value}


def _with_layout(
    inputs: WorkflowInputs,
    system: DesignSystem,
    kind: str | None,
    history: list[DesignPicks],
) -> WorkflowInputs:
    """Without --layout, a design that shows the man rotates through its layout letters."""
    format_id = inputs.format or ("carousel" if kind == "carousel_slide" else DEFAULT_FORMAT)
    spec = system.formats.get(format_id)  # type: ignore[call-overload]
    if spec is None or inputs.layout or not spec.layouts or inputs.no_person:
        return inputs
    seed = "|".join([format_id, inputs.headline or "", inputs.subheadline or "", inputs.stat or ""])
    if format_id == "carousel":
        number, _, total = (inputs.slide or "1/1").partition("/")
        middle = number.strip() not in ("1", total.strip())
        if inputs.slide_role == "tip" or (not inputs.slide_role and middle):
            return inputs  # a middle slide shows no person and has no layout
        seed = f"carousel|{total.strip()}"  # the first and last slides share one layout
    options = [
        letter for letter in spec.layouts
        if not (inputs.pose and system.layouts[letter].split_poses)
    ]
    if inputs.visual and "A" in options:
        options = ["A"]  # the system visual belongs to layout A
    return replace(inputs, layout=choose_layout(options or list(spec.layouts), history, seed))


def prepare_workflow(
    workflow_id: str, inputs: WorkflowInputs, settings: Settings
) -> PreparedWorkflow:
    """Validate inputs and build the ImageRequest; creates no job and calls no provider."""
    spec = get_workflow(workflow_id)
    _check_inputs(spec, inputs)
    if inputs.direction and spec.designed:
        return _prepare_direction(spec, inputs, settings)
    if inputs.post_format and spec.designed:
        return _prepare_format(spec, inputs, settings)
    root = settings.references_dir
    # Capabilities only: no API key is needed and no provider call is made here.
    capabilities: ProviderCapabilities = get_provider(
        settings.image_provider, settings
    ).capabilities
    scene_prompt = inputs.prompt.strip()
    recorded: dict[str, str | bool] = {"scenePrompt": scene_prompt} if scene_prompt else {}
    service = (inputs.service or "").strip() or None
    if service:
        recorded["service"] = service

    system: DesignSystem | None = None
    design: DesignChoice | None = None
    look = DesignLook()
    history: list[DesignPicks] = []
    seed = ""
    identity_set = inputs.identity_set
    aspect: str = inputs.aspect_ratio or spec.default_aspect
    if spec.designed:
        system = load_design_system(settings.design_system_file)
        kind = inputs.kind or (KIND_BY_VARIANT[inputs.variant] if inputs.variant else None)
        if inputs.history is not None:
            history = inputs.history
        else:
            history = flatten(recent_packages(settings.packages_dir))
        inputs = _with_layout(inputs, system, kind, history)
        design = _check_source(resolve_design(inputs, system, kind=kind), settings)
        identity_set = _design_identity_set(design, inputs, settings)
        aspect = _design_aspect(design, system, inputs.aspect_ratio)
        seed = _variety_seed(design)
        look = choose_look(
            design,
            system,
            # Without --scene, a given --prompt is the scene (as before the pools existed).
            scene=inputs.scene or scene_prompt or None,
            wardrobe=inputs.wardrobe,
            props=inputs.props,
            history=history,
            seed=seed,
            context=inputs.context or _context(inputs),
        )
        recorded.update(_recorded_design(design, look))
        recorded["personShown"] = design.person
    else:
        recorded["personShown"] = bool(identity_set)  # photo workflows always show the person
    want_logo = inputs.logo or spec.designed

    identity: list[ReferenceImage] = []
    if identity_set:
        # Primary photos first, capped by IMAGE_IDENTITY_REFS_MAX and the provider's limit.
        identity_max = min(capabilities.max_identity_refs, settings.image_identity_refs_max)
        identity = _identity_refs(identity_set, identity_max, design, settings)
        recorded["identityRefs"] = str(len(identity))
        recorded["identitySet"] = load_set(identity_set, root).set_id

    # All reference images together must fit the model's limit (14). Identity photos always
    # stay; when it gets too many, style images are dropped first. The logo is not sent.
    limit = min(capabilities.max_total_refs or MAX_REFERENCE_IMAGES, MAX_REFERENCE_IMAGES)
    total_left = limit - len(identity)
    if total_left < 0:
        raise WorkflowError(
            f"{len(identity)} identity photos are more than the {limit} reference images the "
            "model accepts; lower IMAGE_IDENTITY_REFS_MAX."
        )
    brand = _load_brand_if_present(settings)
    logo = _logo(settings, brand) if want_logo else None
    if logo is not None:
        recorded["logo"] = logo.describe()
    person_shown = bool(recorded["personShown"])
    style: list[ReferenceImage] = []
    style_sets: list[str] = []
    if design is not None and system is not None:
        # Up to 3 style images that fit the format, rotated between packages.
        fits = system.formats[design.format]
        wanted = min(
            inputs.style_count or fits.style_refs,
            fits.style_refs,
            capabilities.max_style_refs,
            total_left,
            PERSON_STYLE_REFS if design.person else fits.style_refs,
        )
        names = [inputs.style_set] if inputs.style_set else fits.style_sets
        style, style_sets = select_rotating_style_refs(
            names,
            wanted,
            root,
            avoid=[asset_id for picks in history for asset_id in picks.style_refs],
            seed=f"{seed}|style",
            strict=bool(inputs.style_set),
            role=design.slide_role if fits.style_by_role else None,
            person=design.person,
        )
    else:
        style_set = inputs.style_set or spec.default_style_set
        if style_set and "style" in spec.ref_categories:
            wanted = min(
                inputs.style_count or DEFAULT_STYLE_COUNT, capabilities.max_style_refs, total_left,
                PERSON_STYLE_REFS if person_shown else DEFAULT_STYLE_COUNT,
            )
            if wanted > 0:
                style = select_style_refs(style_set, wanted, root, person=person_shown)
                style_sets = [load_set(style_set, root).set_id]

    object_budget = min(capabilities.max_object_refs, total_left)
    if capabilities.max_object_and_style_refs is not None:
        object_budget = min(object_budget, capabilities.max_object_and_style_refs - len(style))
    product: list[ReferenceImage] = []
    if inputs.product_set:
        if object_budget < 1:
            raise WorkflowError("No room for product images; lower --style-count.")
        product = select_set_refs(inputs.product_set, object_budget, root, ref_type="product")
        recorded["productSet"] = load_set(inputs.product_set, root).set_id
    series: list[ReferenceImage] = []
    if design is not None:
        first = _first_slide_ref(design, inputs, settings)
        series = [first] if first is not None else []
        if first is not None:
            recorded["firstSlide"] = first.source
    # Over the limit: drop the style examples first, then slide 1; never identity photos.
    # Slide 1 also counts toward the provider's style limit.
    over = max(
        len(identity) + len(product) + len(style) + len(series) - limit,
        len(style) + len(series) - capabilities.max_style_refs,
    )
    if over > 0:
        dropped = min(over, len(style))
        style = style[: len(style) - dropped]
        series = series[: len(series) - (over - dropped)] if over > dropped else series
    if style:
        recorded["styleSet"] = ", ".join(style_sets)

    if inputs.variant:
        recorded["variant"] = inputs.variant
    if inputs.headline:
        recorded["headline"] = inputs.headline

    counts = RefCounts(
        identity=len(identity),
        product=len(product),
        style=len(style),
        series=len(series),
    )
    company = load_company(settings.company_file)
    text: TextOverlay | None = None
    if design is not None and system is not None and use_text_overlay(
        settings.text_overlay, capabilities.draws_text
    ):
        # Checked now (zones, fonts, every text fits), so a problem stops before any cost.
        text = prepare_text_overlay(design, system, brand, company, aspect_ratio=aspect)
        recorded["textOverlay"] = text.describe()
        recorded["textBoxes"] = json.dumps(text.boxes())
    picks: DesignPicks | None = None
    if design is not None and system is not None:
        prompt = build_design_prompt(
            design,
            look,
            system,
            counts,
            brand,
            aspect_ratio=aspect,
            details=scene_prompt if inputs.scene else None,
            company=company,
            logo=logo is not None,
            text_areas=text.areas() if text is not None else None,
            identity_text=capabilities.identity_prompt,
        )
        picks = DesignPicks.from_recorded(recorded, [ref.asset_id for ref in style])
    else:
        prompt = build_prompt(
            spec, inputs.prompt, counts, brand, service=service, company=company,
            logo=logo is not None,
        )
    request = ImageRequest(
        prompt=prompt,
        aspect_ratio=aspect,  # type: ignore[arg-type]
        image_size=settings.image_design_size if spec.designed else "1K",
        count=inputs.count,
        identity_refs=identity,
        object_refs=product,
        style_refs=style + series,
        person=person_shown,
    )
    return PreparedWorkflow(
        spec=spec,
        request=request,
        product_refs=product,
        logo=logo,
        text=text,
        references=job_references(request, series),
        inputs=recorded,
        picks=picks,
        person_shown=person_shown,
    )


def format_settings(chosen: PostFormat, settings: Settings,
                    slide_type: str | None = None) -> Settings:
    """The provider of one post format (or slide): the format's own, never swapped for another
    (an unreachable provider fails that part). No image slot: the app renders it alone
    (template, free). IMAGE_PROVIDER=mock (local tests) stays mock for pictures."""
    image, _ = chosen.canvas(slide_type)
    if image is None:
        return settings.model_copy(update={"image_provider": "template"})
    provider = chosen.provider or settings.image_provider
    if settings.image_provider in ("mock", provider):
        return settings
    update: dict[str, str] = {"image_provider": provider}
    if provider == "openrouter":  # Nano Banana 2 via OpenRouter (CAROUSEL_IMAGE_MODEL)
        update["image_model"] = settings.carousel_image_model
    return settings.model_copy(update=update)


def _copy_texts(copy: dict[str, object], topic: str | None) -> list[str]:
    """What the reader sees (and the topic): none of it may go into the image prompt."""
    skip = ("illustration", "source", "icon")
    texts = [topic or ""]
    for name, value in copy.items():
        if name not in skip:
            texts += [str(item) for item in (value if isinstance(value, list) else [value])]
    return [text for text in texts if text.strip()]


def _prepare_format(
    spec: WorkflowSpec, inputs: WorkflowInputs, settings: Settings,
) -> PreparedWorkflow:
    """A post format as a template: the picture (no text, never the copy or topic) only for its
    image slot, via the format's own provider; the man only in Roman formats; the panel, text
    and icons rendered by the app, then the logo (a carousel: last slide only)."""
    try:
        catalog = load_formats(settings.post_formats_file)
        chosen = catalog.get(str(inputs.post_format))
        copy = json.loads(inputs.format_copy or "{}")
        system = load_design_system(settings.design_system_file)
        image_slot, _ = chosen.canvas(inputs.slide_type)
    except (FormatError, ValueError) as error:
        raise WorkflowError(str(error)) from None
    if not isinstance(copy, dict):
        raise WorkflowError(f"{chosen.id}: the copy must be an object of the format's fields")
    own = format_settings(chosen, settings, inputs.slide_type)
    number = (inputs.slide or "").partition("/")[0].strip()
    step = int(number) - 1 if inputs.slide_type == "body" and number.isdigit() else None
    text = format_overlay(chosen, copy, system, theme=catalog.themes[chosen.theme],
                          slide_type=inputs.slide_type, step=step)
    recorded: dict[str, str | bool] = {
        "postFormat": chosen.id, "theme": chosen.theme, "personShown": chosen.roman,
        "textOverlay": text.describe(), "textBoxes": json.dumps(text.boxes()),
    }
    if inputs.slide_type:
        recorded["slideType"] = inputs.slide_type
    if inputs.slide:
        recorded["slide"] = inputs.slide
    logo = _logo(settings, _load_brand_if_present(settings)) if inputs.logo else None
    if logo is not None:
        recorded["logo"] = logo.describe()
    if image_slot is None:
        prompt = f"{chosen.id}: no picture; the app renders the template"
        recorded["picture"] = "none (template only, free)"
    else:
        illustration = copy.get("illustration") or inputs.prompt
        try:
            prompt = image_prompt(
                chosen, catalog,
                illustration=illustration if isinstance(illustration, str) else None,
                seed=inputs.request or inputs.topic or "",
                copy_texts=_copy_texts(copy, inputs.topic),
            )
        except FormatError as error:
            raise WorkflowError(str(error)) from None
    request = ImageRequest(
        prompt=prompt,
        aspect_ratio=chosen.slot_aspect(inputs.slide_type),  # type: ignore[arg-type]
        image_size=settings.image_design_size if image_slot is not None else "1K",
        count=inputs.count,
        person=chosen.roman,
    )
    return PreparedWorkflow(
        spec=spec, request=request, logo=logo, text=text,
        references=job_references(request), inputs=recorded, person_shown=chosen.roman,
        settings=own,
    )


def _prepare_direction(
    spec: WorkflowSpec, inputs: WorkflowInputs, settings: Settings,
) -> PreparedWorkflow:
    """Phase D: a design direction. The picture via the direction's own provider (none: the
    free template; Roman's real photo: no generation), then the whole design drawn by the app
    and checked; creates no job and calls no provider."""
    try:
        catalog = load_directions()
        direction = catalog.get(str(inputs.direction))
        copy = json.loads(inputs.format_copy or "{}")
    except (DirectionError, ValueError) as error:
        raise WorkflowError(str(error)) from None
    if not isinstance(copy, dict):
        raise WorkflowError(f"{direction.id}: the copy must be an object of the layout's fields")
    seed = inputs.topic or inputs.request or ""
    role = inputs.slide_type if direction.format == "carousel" else None
    combination: Combination | None = None
    try:
        if direction.visual.subject == "roman_higgsfield":
            combination = (parse_combination(inputs.roman_combination)
                           if inputs.roman_combination else pick_combination(seed, [])[0])
        name, layout = direction_layout(
            direction, platform=inputs.direction_platform, seed=seed, role=role,
            side=combination.side if combination is not None else None)
    except (DirectionError, RomanPromptError) as error:
        raise WorkflowError(str(error)) from None
    picture = has_picture(direction, layout, role)
    designer: DesignerInputs | None = None
    recorded: dict[str, str | bool] = {"direction": direction.id, "layout": name,
                                       "personShown": False}
    try:
        # Roman: Higgsfield Soul 2.0 (his saved character), never a real photo, never another
        # provider (v6 R5: the only route for Roman).
        route = check_route(direction, settings, requires_roman=inputs.requires_roman)
        recorded["route"] = route
        own = direction_settings(direction, picture, settings)
        person = direction.roman and picture
        mode = "composite" if person or not picture else (
            "composite" if inputs.design_mode == "composite" else
            "designer" if inputs.design_mode == "designer" else default_mode())
        layout = _varied(direction, layout, catalog, inputs.variation)
        if not picture:
            prompt = f"{direction.id}: no picture generated; the app renders the design"
        elif person and combination is not None:
            prompt = roman_prompt_text(combination)
            recorded["romanCombination"] = combination.id
            recorded["identity"] = (f"Higgsfield character {character_token()} "
                                    "(no identity photos sent)")
            recorded["aiDisclosure"] = AI_DISCLOSURE
        elif person:
            raise WorkflowError(f"{direction.id} shows Roman without a Higgsfield combination "
                                "(S-x/BG-x/P-x/H-x): plan it again")
        else:
            picture_text = illustration_prompt(direction, catalog, copy, inputs.prompt or None)
            if inputs.variation and Variation.parse(inputs.variation).side == "R" and (
                    can_mirror(direction)):
                picture_text = mirror_words(picture_text)
            designer = _designer(direction, layout, catalog, picture_text, copy, inputs, own,
                                 role, mode)
            prompt = designer.prompt
            recorded.update(designer.record())
    except (DirectionJobError, ReferenceLibraryError, DesignerPromptError,
            RoutingError, DirectionError) as error:
        raise WorkflowError(str(error)) from None
    number = (inputs.slide or "").partition("/")[0].strip()
    design = DirectionDesign(direction=direction.id, layout=name, copy=copy,
                             platform=inputs.direction_platform,
                             step=int(number) - 1 if number.isdigit() else 0, mode=mode,
                             texts=designer.texts if designer is not None else [],
                             variation=inputs.variation,
                             reuse_scene=mode == "designer" and inputs.design_attempt >= int(
                                 text_check_config().get("attempts", 2)))
    recorded["personShown"] = person
    recorded["design"] = design.to_json()
    recorded["designMode"] = mode
    if mode == "designer" and inputs.design_attempt > 1:
        recorded["designAttempt"] = str(inputs.design_attempt)
    if inputs.variation:
        recorded["variation"] = inputs.variation
    if inputs.slide:
        recorded["slide"] = inputs.slide
    aspect: AspectRatio = picture_aspect(direction, layout, catalog) if picture else "4:5"
    if combination is not None or mode == "designer":  # the canvas aspect: the model draws the
        # whole ad (designer) or higgsfield_soul maps and crops it (Roman)
        aspect = cast(AspectRatio, CANVAS[direction.format])
    request = ImageRequest(
        prompt=prompt,
        object_refs=designer.object_refs if designer is not None else [],
        style_refs=designer.style_refs if designer is not None else [],
        options=({"combination": combination.id, "side": combination.side}
                 if combination is not None else
                 # v6 R3.4: the text read back costs one vision check (in the estimate)
                 {"designMode": mode, "textCheckUsd": f"{estimated_check_usd():.4f}"}
                 if picture else {}),
        aspect_ratio=aspect,
        image_size=settings.image_design_size if picture else "1K",
        count=inputs.count,
        person=person,
    )
    return PreparedWorkflow(spec=spec, request=request, references=job_references(request),
                            inputs=recorded, person_shown=person, settings=own, design=design)


def _varied(direction: Direction, layout: Layout, catalog: DirectionCatalog,
            variation: str | None) -> Layout:
    """v6 R3.5: the layout in the package's variation (unchanged without one)."""
    if not variation:
        return layout
    return apply_variation(direction, layout, Variation.parse(variation), catalog)


def _designer(direction: Direction, layout: Layout, catalog: DirectionCatalog, picture: str,
              copy: dict[str, Any], inputs: WorkflowInputs, settings: Settings,
              role: str | None, mode: str = "designer") -> DesignerInputs:
    """v6 R3.3/R3.4: the designer's prompt (designer mode: with the guide's colours, the logo
    and the masked references; composite mode: the scene only, no image inputs)."""
    brand = load_brand(settings.references_dir)
    try:
        logo: Path | None = logo_file(brand, settings.references_dir)
    except DesignRenderError:
        logo = None  # named as missing; a paid job then stops
    return designer_inputs(
        direction, layout, catalog, picture=picture, topic=inputs.topic or "", copy=copy,
        references_dir=settings.references_dir, logo_path=logo,
        cache_dir=settings.output_dir.parent / "cache", role=role,
        mock=settings.image_provider == "mock",
        mode="composite" if mode == "composite" else "designer")


def run_workflow(
    workflow_id: str, inputs: WorkflowInputs, settings: Settings, *, cold_start: bool = True
) -> Job:
    """Prepare the workflow (fails early on bad inputs), then run it as an image job.

    cold_start=False: it follows another job of the same build on a warm worker.
    v6 R3.4 (2026-10-21): a designer-mode image that fails its checks gets one regeneration
    (both attempts count toward the cost); when that fails too, its scene is reused in composite
    mode without a call where the layout allows it (DirectionDesign.reuse_scene), else one
    composite generation; then the image fails with its reason. The returned job is the last
    one, with the earlier attempts named in its notes."""
    prepared = prepare_workflow(workflow_id, inputs, settings)
    job = _timed(prepared, inputs, settings, cold_start, inputs.design_attempt)
    if prepared.design is None or prepared.design.mode != "designer":
        return job
    attempts = int(text_check_config().get("attempts", 2))
    failed: list[str] = []
    attempt = inputs.design_attempt
    while job.status == "failed" and DESIGNER_CHECK_FAILED in (job.error or ""):
        failed.append(f"designer attempt {attempt} ({job.job_id}): {job.error}")
        attempt += 1
        retry = (replace(inputs, design_attempt=attempt) if attempt <= attempts else
                 replace(inputs, design_mode="composite"))
        prepared = prepare_workflow(workflow_id, retry, settings)
        job = _timed(prepared, retry, settings, False, attempt)
        if retry.design_mode == "composite":
            break
    if failed:
        job.notes.append("Designer mode: " + " | ".join(failed)
                         + ("; composite mode used" if attempt > attempts else ""))
        job.save()
    return job


def _timed(prepared: PreparedWorkflow, inputs: WorkflowInputs, settings: Settings,
           cold_start: bool, attempt: int) -> Job:
    """One image job and one progress line on stderr for a paid provider (row, attempt,
    seconds, result), so a parallel build shows its progress without verbose output."""
    from content_automation.registry import runtime

    started = time.monotonic()
    job = _run_prepared(prepared, inputs, settings, cold_start)
    provider = (prepared.settings or settings).image_provider
    if provider not in ("mock", "template"):
        scope = runtime.current()
        row = (scope.item if scope is not None else None) or inputs.topic or "-"
        mode = prepared.design.mode if prepared.design is not None else provider
        result = ("passed" if job.status == "completed" else
                  f"failed: {' '.join((job.error or '').split())[:100]}")
        print(f"[image] {row} {inputs.slide or ''} attempt {attempt} ({mode}): "
              f"{time.monotonic() - started:.0f}s, {result}", file=sys.stderr, flush=True)
    return job


def _run_prepared(prepared: PreparedWorkflow, inputs: WorkflowInputs, settings: Settings,
                  cold_start: bool) -> Job:
    return run_image_job(
        prepared.request,
        prepared.settings or settings,
        workflow_id=prepared.spec.workflow_id,
        workflow_version=prepared.spec.version,
        user_request=(
            inputs.request or inputs.prompt.strip() or inputs.headline or inputs.stat or None
        ),
        product_asset_ids=prepared.product_asset_ids,
        brand_asset_ids=prepared.brand_asset_ids,
        inputs=prepared.inputs,
        logo=prepared.logo,
        text=prepared.text,
        references=prepared.references,
        cold_start=cold_start,
        design=prepared.design,
    )
