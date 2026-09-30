"""Image workflow definitions: inputs, defaults and the reference categories each one uses."""

from dataclasses import dataclass
from typing import Literal

from content_automation.ai.image import AspectRatio

InputName = Literal[
    "identity_set", "product_set", "style_set", "variant", "headline", "logo", "service"
]
RefCategory = Literal["identity", "product", "brand", "style"]
DEFAULT_STYLE_COUNT = 3

# CLI flag for each input, used in error messages.
INPUT_FLAGS: dict[InputName, str] = {
    "identity_set": "--set",
    "product_set": "--product",
    "style_set": "--style",
    "variant": "--variant",
    "headline": "--headline",
    "logo": "--logo",
    "service": "--service",
}


class WorkflowError(ValueError):
    """Unknown workflow or missing/unsupported inputs; raised before any job is created."""


@dataclass(frozen=True)
class WorkflowSpec:
    workflow_id: str
    version: str
    description: str
    required_inputs: tuple[InputName, ...]
    optional_inputs: tuple[InputName, ...]
    default_aspect: AspectRatio
    ref_categories: tuple[RefCategory, ...]
    variants: tuple[str, ...] = ()
    default_variant: str | None = None
    default_style_set: str | None = None


WORKFLOWS: dict[str, WorkflowSpec] = {
    spec.workflow_id: spec
    for spec in (
        WorkflowSpec(
            workflow_id="person_lifestyle",
            version="1",
            description="Photo of the person in a real-life scene.",
            required_inputs=("identity_set",),
            optional_inputs=("style_set",),
            default_aspect="4:5",
            ref_categories=("identity", "style"),
        ),
        WorkflowSpec(
            workflow_id="person_service",
            version="1",
            description="Photo of the person providing or presenting a company service.",
            required_inputs=("identity_set", "service"),
            optional_inputs=(),
            default_aspect="4:5",
            ref_categories=("identity",),
        ),
        WorkflowSpec(
            workflow_id="social_creative",
            version="1",
            description="Designed social post, ad or carousel slide in the brand style.",
            required_inputs=(),
            optional_inputs=(
                "identity_set", "product_set", "style_set", "variant", "headline", "logo",
            ),
            default_aspect="4:5",
            ref_categories=("identity", "product", "brand", "style"),
            variants=("post", "ad", "carousel_slide"),
            default_variant="post",
            default_style_set="creative/facebook_ads",
        ),
    )
}


def get_workflow(workflow_id: str) -> WorkflowSpec:
    spec = WORKFLOWS.get(workflow_id)
    if spec is None:
        raise WorkflowError(
            f"Unknown workflow '{workflow_id}'. Use one of: {', '.join(sorted(WORKFLOWS))}."
        )
    return spec
