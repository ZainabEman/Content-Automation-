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
    select_set_refs,
    select_style_refs,
)
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

AD_VARIANTS = 3  # ads are made as 3 variants unless a count is given
# --variant is the old name of --kind.
KIND_BY_VARIANT = {"post": "organic", "ad": "ad", "carousel_slide": "carousel_slide"}


@dataclass
class WorkflowInputs:
    prompt: str
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
    slide: str | None = None  # "N/TOTAL"
    slide_role: str | None = None
    # The person to show when the design has one and no identity_set is given (from a brief);
    # unlike identity_set it is simply unused by designs without a person.
    fallback_identity_set: str | None = None

    def provided(self) -> set[InputName]:
        values: dict[InputName, str | bool | None] = {
            "identity_set": self.identity_set,
            "product_set": self.product_set,
            "style_set": self.style_set,
            "variant": self.variant,
            "headline": self.headline,
            "logo": self.logo,
            "service": (self.service or "").strip() or None,
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
            "slide": self.slide,
            "slide_role": self.slide_role,
        }
        return {name for name, value in values.items() if value not in (None, "", False)}


@dataclass
class PreparedWorkflow:
    spec: WorkflowSpec
    request: ImageRequest
    product_refs: list[ReferenceImage] = field(default_factory=list)
    brand_refs: list[ReferenceImage] = field(default_factory=list)
    inputs: dict[str, str | bool] = field(default_factory=dict)

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
    if not inputs.prompt.strip():
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
            f"{design.label} shows no person: remove --set, or use --layout B, C or D."
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
    allowed = system.formats[design.kind].aspects
    if wanted is None:
        return allowed[0]
    if wanted not in allowed:
        raise WorkflowError(
            f"--aspect for --kind {design.kind} must be one of: {', '.join(allowed)}."
        )
    return wanted


def _recorded_design(design: DesignChoice) -> dict[str, str | bool]:
    values = {
        "kind": design.kind,
        "layout": design.layout,
        "pose": design.pose,
        "highlight": ", ".join(design.highlight),
        "subheadline": design.subheadline,
        "subHighlight": design.sub_highlight,
        "cta": design.cta,
        "ctaIcon": design.cta_icon,
        "icons": ", ".join(design.icons),
        "visual": design.visual,
        "slide": "/".join(str(part) for part in design.slide) if design.slide else None,
        "slideRole": design.slide_role,
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
    recorded: dict[str, str | bool] = {"scenePrompt": inputs.prompt.strip()}
    service = (inputs.service or "").strip() or None
    if service:
        recorded["service"] = service

    system: DesignSystem | None = None
    design: DesignChoice | None = None
    identity_set = inputs.identity_set
    aspect: str = inputs.aspect_ratio or spec.default_aspect
    if spec.designed:
        system = load_design_system(settings.design_system_file)
        variant = inputs.variant or spec.default_variant or "post"
        design = resolve_design(inputs, system, kind=inputs.kind or KIND_BY_VARIANT[variant])
        identity_set = _design_identity_set(design, inputs, settings)
        aspect = _design_aspect(design, system, inputs.aspect_ratio)
        recorded.update(_recorded_design(design))
    want_logo = inputs.logo or spec.designed

    identity: list[ReferenceImage] = []
    if identity_set:
        # Primary photos first, capped by IMAGE_IDENTITY_REFS_MAX and the provider's limit.
        identity_max = min(capabilities.max_identity_refs, settings.image_identity_refs_max)
        identity = _identity_refs(identity_set, identity_max, design, settings)
        recorded["identitySet"] = load_set(identity_set, root).set_id

    # Room left when the provider caps all reference images together (logo counted first).
    total_left = (
        capabilities.max_total_refs - len(identity) - (1 if want_logo else 0)
        if capabilities.max_total_refs is not None
        else None
    )
    brand = _load_brand_if_present(settings)
    style: list[ReferenceImage] = []
    style_set = inputs.style_set or spec.default_style_set
    if style_set and "style" in spec.ref_categories:
        wanted = min(inputs.style_count or DEFAULT_STYLE_COUNT, capabilities.max_style_refs)
        if total_left is not None:
            wanted = min(wanted, total_left)
        if wanted > 0:
            style = select_style_refs(style_set, wanted, root)
            recorded["styleSet"] = load_set(style_set, root).set_id

    logo: list[ReferenceImage] = []
    if want_logo:
        logo = [select_logo_ref(root, preferred=brand.logo_file if brand else None)]
        recorded["logo"] = True
    object_budget = capabilities.max_object_refs - len(logo)
    if capabilities.max_object_and_style_refs is not None:
        object_budget = min(
            object_budget, capabilities.max_object_and_style_refs - len(style) - len(logo)
        )
    if total_left is not None:
        object_budget = min(object_budget, total_left - len(style))
    product: list[ReferenceImage] = []
    if inputs.product_set:
        if object_budget < 1:
            raise WorkflowError("No room for product images; lower --style-count.")
        product = select_set_refs(inputs.product_set, object_budget, root, ref_type="product")
        recorded["productSet"] = load_set(inputs.product_set, root).set_id

    if inputs.variant:
        recorded["variant"] = inputs.variant
    if inputs.headline:
        recorded["headline"] = inputs.headline

    counts = RefCounts(
        identity=len(identity), product=len(product), logo=len(logo), style=len(style)
    )
    company = load_company(settings.company_file)
    if design is not None and system is not None:
        prompt = build_design_prompt(
            design, system, inputs.prompt, counts, brand, aspect_ratio=aspect, company=company
        )
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
        style_refs=style,
    )
    return PreparedWorkflow(
        spec=spec, request=request, product_refs=product, brand_refs=logo, inputs=recorded
    )


def run_workflow(workflow_id: str, inputs: WorkflowInputs, settings: Settings) -> Job:
    """Prepare the workflow (fails early on bad inputs), then run it as an image job."""
    prepared = prepare_workflow(workflow_id, inputs, settings)
    return run_image_job(
        prepared.request,
        settings,
        workflow_id=prepared.spec.workflow_id,
        workflow_version=prepared.spec.version,
        user_request=inputs.request or inputs.prompt.strip(),
        product_asset_ids=prepared.product_asset_ids,
        brand_asset_ids=prepared.brand_asset_ids,
        inputs=prepared.inputs,
    )
