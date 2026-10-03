"""Named image workflows: check inputs, pick references, build the prompt, run the job."""

from dataclasses import dataclass, field

from content_automation.ai.image import (
    ASPECT_RATIOS,
    MAX_COUNT,
    ImageRequest,
    ProviderCapabilities,
    ReferenceImage,
    get_provider,
)
from content_automation.core.config import Settings
from content_automation.core.jobs import Job
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
from content_automation.workflows.design_system import (
    DesignChoice,
    DesignSystem,
    load_design_system,
    resolve_design,
)
from content_automation.workflows.image_job import run_image_job
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
from content_automation.workflows.variety import (
    DesignLook,
    DesignPicks,
    choose_look,
    flatten,
    recent_packages,
)

AD_VARIANTS = 3  # ads are made as 3 variants unless a count is given
MAX_REFERENCE_IMAGES = 14  # the image model's limit for all reference images together
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
    steps: str | None = None  # "|"-separated
    slide: str | None = None  # "N/TOTAL"
    slide_role: str | None = None
    # Variable parts: a pool ID from the design system or own words; picked when left out.
    scene: str | None = None
    wardrobe: str | None = None
    props: str | None = None
    # The person to show when the design has one and no identity_set is given (from a brief);
    # unlike identity_set it is simply unused by designs without a person.
    fallback_identity_set: str | None = None
    # Carousel slides 2+: slide 1's image ("<jobId>/image-1.png"), attached as a style image.
    first_slide: str | None = None
    # Picks to avoid, newest first (from a brief's package); default: the newest packages.
    history: list[DesignPicks] | None = None

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
            "steps": self.steps,
            "slide": self.slide,
            "slide_role": self.slide_role,
            "scene": self.scene,
            "wardrobe": self.wardrobe,
            "props": self.props,
            "first_slide": self.first_slide,
        }
        return {name for name, value in values.items() if value not in (None, "", False)}


@dataclass
class PreparedWorkflow:
    spec: WorkflowSpec
    request: ImageRequest
    product_refs: list[ReferenceImage] = field(default_factory=list)
    brand_refs: list[ReferenceImage] = field(default_factory=list)
    inputs: dict[str, str | bool] = field(default_factory=dict)
    picks: DesignPicks | None = None  # designs: what was used from the pools

    @property
    def product_asset_ids(self) -> list[str]:
        return [ref.asset_id for ref in self.product_refs]

    @property
    def brand_asset_ids(self) -> list[str]:
        return [ref.asset_id for ref in self.brand_refs]


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


def _check_source(design: DesignChoice, settings: Settings) -> None:
    """A stat is refused unless its number is written in the research article it names."""
    if design.source is None:
        return
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


def _first_slide_ref(design: DesignChoice, inputs: WorkflowInputs, settings: Settings) -> (
    ReferenceImage | None
):
    """Slide 1's image for the later slides of a carousel: same scene, colours and decor."""
    if not inputs.first_slide:
        return None
    if design.format != "carousel" or design.slide_role == "hook":
        raise WorkflowError("--first-slide is for carousel slides after the first.")
    try:
        found = resolve_start_image(inputs.first_slide, settings)
    except StartImageError as error:
        raise WorkflowError(f"--first-slide: {error}") from None
    return ReferenceImage(asset_id=found.asset_id, path=found.path, source=found.source)


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
        "slide": "/".join(str(part) for part in design.slide) if design.slide else None,
        "slideRole": design.slide_role,
        **look.ids(),
    }
    return {name: value for name, value in values.items() if value}


def prepare_workflow(
    workflow_id: str, inputs: WorkflowInputs, settings: Settings
) -> PreparedWorkflow:
    """Validate inputs and build the ImageRequest; creates no job and calls no provider."""
    spec = get_workflow(workflow_id)
    _check_inputs(spec, inputs)
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
        design = resolve_design(inputs, system, kind=kind)
        _check_source(design, settings)
        identity_set = _design_identity_set(design, inputs, settings)
        aspect = _design_aspect(design, system, inputs.aspect_ratio)
        if inputs.history is not None:
            history = inputs.history
        else:
            history = flatten(recent_packages(settings.packages_dir))
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

    # All reference images together must fit the model's limit (14). Identity photos and
    # the logo always stay; when it gets too many, style images are dropped first.
    limit = min(capabilities.max_total_refs or MAX_REFERENCE_IMAGES, MAX_REFERENCE_IMAGES)
    total_left = limit - len(identity) - (1 if want_logo else 0)
    if total_left < 0:
        raise WorkflowError(
            f"{len(identity)} identity photos plus the logo are more than the {limit} "
            "reference images the model accepts; lower IMAGE_IDENTITY_REFS_MAX."
        )
    brand = _load_brand_if_present(settings)
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
        )
    else:
        style_set = inputs.style_set or spec.default_style_set
        if style_set and "style" in spec.ref_categories:
            wanted = min(
                inputs.style_count or DEFAULT_STYLE_COUNT, capabilities.max_style_refs, total_left
            )
            if wanted > 0:
                style = select_style_refs(style_set, wanted, root)
                style_sets = [load_set(style_set, root).set_id]

    logo: list[ReferenceImage] = []
    if want_logo:
        logo = [select_logo_ref(root, preferred=brand.logo_file if brand else None)]
        recorded["logo"] = True
    object_budget = min(capabilities.max_object_refs - len(logo), total_left)
    if capabilities.max_object_and_style_refs is not None:
        object_budget = min(
            object_budget, capabilities.max_object_and_style_refs - len(style) - len(logo)
        )
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
    # Over the limit: drop the style examples first, then slide 1; never identity or logo.
    over = len(identity) + len(logo) + len(product) + len(style) + len(series) - limit
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
        logo=len(logo),
        style=len(style),
        series=len(series),
    )
    company = load_company(settings.company_file)
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
        )
        picks = DesignPicks.from_recorded(recorded, [ref.asset_id for ref in style])
    else:
        prompt = build_prompt(
            spec, inputs.prompt, counts, brand, service=service, company=company
        )
    request = ImageRequest(
        prompt=prompt,
        aspect_ratio=aspect,  # type: ignore[arg-type]
        image_size=settings.image_design_size if spec.designed else "1K",
        count=inputs.count,
        identity_refs=identity,
        object_refs=product + logo,
        style_refs=style + series,
    )
    return PreparedWorkflow(
        spec=spec,
        request=request,
        product_refs=product,
        brand_refs=logo,
        inputs=recorded,
        picks=picks,
    )


def run_workflow(workflow_id: str, inputs: WorkflowInputs, settings: Settings) -> Job:
    """Prepare the workflow (fails early on bad inputs), then run it as an image job."""
    prepared = prepare_workflow(workflow_id, inputs, settings)
    return run_image_job(
        prepared.request,
        settings,
        workflow_id=prepared.spec.workflow_id,
        workflow_version=prepared.spec.version,
        user_request=(
            inputs.request or inputs.prompt.strip() or inputs.headline or inputs.stat or None
        ),
        product_asset_ids=prepared.product_asset_ids,
        brand_asset_ids=prepared.brand_asset_ids,
        inputs=prepared.inputs,
    )
