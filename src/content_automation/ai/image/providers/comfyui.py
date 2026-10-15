"""ComfyUI image adapter: a workflow in ComfyUI API format, run on a RunPod Serverless
endpoint with runpod-workers/worker-comfyui (providers/runpod.py).

The workflow: IMAGE_MODEL when it names one in config/comfyui.json (qwen_image_2512 or
z_image_turbo), else defaultWorkflow (z_image_turbo), so an OpenRouter IMAGE_MODEL never blocks
ComfyUI (workflow_for; the dry run and the job record name the workflow used). Each
workflow is an API-format JSON plus a mapping file naming the node and input of every value the
app sets (prompt, negative, seed, width, height, steps, cfg, lora_name, lora_strength): values
are filled through the mapping, never by string replacement.

Identity: the person's trained LoRA. No reference images are sent (all reference limits are 0);
the prompt names the person by the LoRA trigger word (capabilities.identity_prompt). An image
without the person bypasses the LoRA node. Live fix: an image with the person is only a clean
studio photo built from personPhoto (the template, an outfit and a pose from config; never the
post's copy or scene), made at personPhoto.size and returned unscaled: the app composes the post
(workflows/compose.py).
Text: the model draws none (draws_text False), so the app overlays it
(workflows/text_overlay.py).

Size: each aspect ratio has a model-friendly size (multiples of 16, about 1-1.6 MP); the result
is scaled to the target size (long side per IMAGE_DESIGN_SIZE) with Pillow Lanczos, optionally
after an upscale-model node added to the workflow (upscaleNode in the config).

Cost: estimated from GPU time (price per second x seconds per image, plus cold start and idle
once per request; a package build sends its images back-to-back, batch_images, so it pays one
cold start). The actual cost is computed from RunPod's delayTime + executionTime (queue time
counts too) and kept with the job. No retry, and never a fallback to another provider: that
would spend money nobody approved.
"""

import base64
import binascii
import copy
import io
import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

from PIL import Image, UnidentifiedImageError
from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.ai.image import (
    AspectRatio,
    GeneratedImage,
    ImageProviderError,
    ImageRequest,
    ImageResult,
    ImageSize,
    ImageTimeoutError,
    ProviderCapabilities,
)
from content_automation.ai.image.providers.runpod import SWITCH, RunPodClient, RunPodJob
from content_automation.core.config import Settings
from content_automation.core.files import CamelModel

_PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_CONFIG = Path("config/comfyui.json")
MappedValue = Literal[
    "prompt", "negative", "seed", "width", "height", "steps", "cfg", "lora_name", "lora_strength"
]
MAPPED: tuple[MappedValue, ...] = (
    "prompt", "negative", "seed", "width", "height", "steps", "cfg", "lora_name", "lora_strength"
)
_UPSCALE_LOADER, _UPSCALE = "900", "901"  # node IDs added when upscaleNode is enabled


class _Model(CamelModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowConfig(_Model):
    workflow: Path  # API-format JSON
    mapping: Path  # node IDs and inputs of the MAPPED values
    seconds_per_image: float = Field(gt=0)  # GPU seconds, warm worker (the cost estimate)
    steps: int = Field(ge=1)
    cfg: float = Field(gt=0)
    lora_name: str = Field(min_length=1)  # in models/loras on the network volume
    lora_sha256: str = ""  # from `ca lora set <local path>` (MANIFEST.json checked)
    lora_local_path: str = ""  # where the LoRA lies on this computer (never committed)
    negative: str = ""
    sizes: dict[AspectRatio, tuple[int, int]] | None = None  # this model's sizes (else global)

    @model_validator(mode="after")
    def _check_sizes(self) -> Self:
        if any(w % 16 or h % 16 or w <= 0 or h <= 0 for w, h in (self.sizes or {}).values()):
            raise ValueError("sizes must be multiples of 16")
        return self


PHOTO_TEMPLATE = (
    "{prefix}{outfit}, {pose}, medium shot from the waist up, centered, facing the camera "
    "slightly turned, filling most of the frame, plain light-grey seamless studio background, "
    "soft even studio light, realistic professional portrait photo, sharp focus on the face, "
    "nothing written anywhere, no objects")
# Words that never go into a person photo (they invite painted text or objects).
PHOTO_BANNED = ("screen", "monitor", "display", "sign", "poster", "billboard", "banner",
                "whiteboard", "hologram", "chart", "document", "logo", "text", "headline",
                "laptop", "phone", "tablet", "ui", "dashboard")


class PersonPhoto(_Model):
    """config/comfyui.json personPhoto: what the model makes of Roman: a clean studio photo."""

    note: str | None = Field(default=None, alias="_note")
    template: str = PHOTO_TEMPLATE
    outfits: list[str] = Field(default_factory=lambda: [
        "dark navy blazer, white open-collar shirt"], min_length=1)
    poses: list[str] = Field(default_factory=lambda: [
        "arms relaxed, confident friendly expression"], min_length=1)
    size: tuple[int, int] = (1024, 1280)

    @model_validator(mode="after")
    def _check(self) -> Self:
        problems = [f"template needs {key}" for key in ("{prefix}", "{outfit}", "{pose}")
                    if key not in self.template]
        banned = re.compile(r"\b(" + "|".join(PHOTO_BANNED) + r")s?\b|[0-9%#]", re.IGNORECASE)
        problems += [f'"{text}" (no numbers, signs or screen words)'
                     for text in (*self.outfits, *self.poses) if banned.search(text)]
        if any(side % 16 or side <= 0 for side in self.size):
            problems.append("size (multiples of 16)")
        if problems:
            raise ValueError("personPhoto: " + ", ".join(problems))
        return self


class ModelFile(_Model):
    """A base model file of a workflow: where it comes from and where the worker reads it."""

    file: str = Field(min_length=1)  # the name in the workflow's loader node
    volume_path: str = Field(min_length=1)  # relative to the volume (/runpod-volume)
    source: str = ""
    size_gb: float = Field(default=0, ge=0)


class UpscaleNode(_Model):
    enabled: bool = False
    model: str = ""  # in models/upscale_models on the network volume


class ComfyUIConfig(_Model):
    gpu: str = Field(min_length=1)
    price_per_second_usd: float = Field(gt=0)
    price_source: str = ""
    cold_start_seconds: float = Field(ge=0)
    idle_seconds: float = Field(ge=0)  # the endpoint's idle timeout, billed after each job
    poll_seconds: float = Field(gt=0)
    timeout_seconds: float = Field(gt=0)  # then the RunPod job is cancelled
    target_long_side: dict[ImageSize, int]
    sizes: dict[AspectRatio, tuple[int, int]]  # what the model renders, multiples of 16
    trigger_word: str = Field(min_length=1)
    lora_strength: float = Field(ge=0, le=2)
    person_prefix: str = "{trigger}, a man, "  # every person prompt starts with it
    group_lora_strength: float = Field(default=0.8, ge=0, le=2)
    group_words: tuple[str, ...] = ("group", "team", "colleagues", "audience", "crowd")
    person_blocked_words: tuple[str, ...] = (
        "screen", "monitor", "display", "sign", "signage", "poster", "billboard", "banner",
        "whiteboard")
    network_volume: str = ""  # the planned size (setup guide)
    models: dict[str, dict[str, ModelFile]] = Field(default_factory=dict)  # per workflow
    person_photo: PersonPhoto = Field(default_factory=PersonPhoto)
    identity_prompt: str = Field(min_length=1)  # "{trigger}" is the trigger word
    upscale_node: UpscaleNode = Field(default_factory=UpscaleNode)
    workflows: dict[str, WorkflowConfig] = Field(min_length=1)
    default_workflow: str = "z_image_turbo"  # when IMAGE_MODEL names no ComfyUI workflow

    @model_validator(mode="after")
    def _check(self) -> Self:
        problems = [
            f"sizes.{aspect} (multiples of 16)"
            for aspect, (width, height) in self.sizes.items()
            if width % 16 or height % 16 or width <= 0 or height <= 0
        ]
        if "{trigger}" not in self.identity_prompt:
            problems.append("{trigger} in identityPrompt")
        if self.upscale_node.enabled and not self.upscale_node.model.strip():
            problems.append("upscaleNode.model (needed when enabled)")
        if self.default_workflow not in self.workflows:
            problems.append(f"defaultWorkflow {self.default_workflow} (not under workflows)")
        if problems:
            raise ValueError("missing or invalid " + ", ".join(problems))
        return self


class NodeInput(_Model):
    node: str = Field(min_length=1)
    input: str = Field(min_length=1)


class LoraBypass(_Model):
    """Without the person: this input takes `source` (the base model) and the LoRA node goes."""

    node: str = Field(min_length=1)
    input: str = Field(min_length=1)
    source: tuple[str, int]


class WorkflowMapping(_Model):
    inputs: dict[MappedValue, NodeInput]
    lora_bypass: LoraBypass
    decode: str = Field(min_length=1)  # the VAE decode node (an upscale node follows it)
    save: str = Field(min_length=1)  # the SaveImage node


@dataclass(frozen=True)
class LoadedWorkflow:
    name: str
    spec: WorkflowConfig
    graph: dict[str, Any]
    mapping: WorkflowMapping


def is_unset(value: str) -> bool:
    """A placeholder like "<set in Step 4>" or an empty value."""
    return not value.strip() or value.strip().startswith("<")


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() or path.exists() else _PROJECT_ROOT / path


def _problems(error: ValidationError) -> str:
    return "; ".join(sorted({
        ".".join(str(part) for part in issue["loc"]) or str(issue["msg"])
        for issue in error.errors(include_url=False)
    }))


def load_config(path: Path = DEFAULT_CONFIG) -> ComfyUIConfig:
    file = _resolve(path)
    try:
        return ComfyUIConfig.model_validate_json(file.read_text(encoding="utf-8"))
    except OSError:
        raise ImageProviderError(
            f"ComfyUI config not found: {path}. Restore config/comfyui.json or set "
            "COMFYUI_CONFIG_FILE in .env."
        ) from None
    except ValidationError as error:
        raise ImageProviderError(f"{file.name} is invalid; check: {_problems(error)}.") from None


def load_workflow(config: ComfyUIConfig, name: str) -> LoadedWorkflow:
    """The workflow JSON and its mapping; every mapped node and input must exist."""
    spec = config.workflows.get(name)
    if spec is None:
        raise ImageProviderError(
            f"IMAGE_MODEL={name} is not a ComfyUI workflow; set IMAGE_MODEL to one of: "
            f"{', '.join(config.workflows)} (config/comfyui.json)."
        )
    try:
        graph = json.loads(_resolve(spec.workflow).read_text(encoding="utf-8"))
        mapping = WorkflowMapping.model_validate_json(
            _resolve(spec.mapping).read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        detail = _problems(error) if isinstance(error, ValidationError) else type(error).__name__
        raise ImageProviderError(
            f"ComfyUI workflow {name} cannot be read ({spec.workflow}, {spec.mapping}): {detail}."
        ) from None
    if not isinstance(graph, dict):
        raise ImageProviderError(f"{spec.workflow} is not a ComfyUI API-format workflow.")
    problems = [f"{key} -> {target.node}.{target.input}" for key, target in mapping.inputs.items()
                if not _has_input(graph, target.node, target.input)]
    problems += [f"{key} (not mapped)" for key in MAPPED if key not in mapping.inputs]
    bypass = mapping.lora_bypass
    if not _has_input(graph, bypass.node, bypass.input) or bypass.source[0] not in graph:
        problems.append(f"loraBypass -> {bypass.node}.{bypass.input} from {bypass.source[0]}")
    problems += [f"{label} node {node}" for label, node in
                 (("decode", mapping.decode), ("save", mapping.save)) if node not in graph]
    if problems:
        raise ImageProviderError(
            f"{spec.mapping} does not match {spec.workflow}: {', '.join(problems)}."
        )
    return LoadedWorkflow(name=name, spec=spec, graph=graph, mapping=mapping)


def _has_input(graph: dict[str, Any], node: str, name: str) -> bool:
    found = graph.get(node)
    return isinstance(found, dict) and isinstance(found.get("inputs"), dict) and (
        name in found["inputs"]
    )


def person_photo_prompt(config: ComfyUIConfig) -> str:
    """The only prompt an image with the person gets: the personPhoto template with the
    trigger prefix, the first outfit and the first pose (nothing from the post)."""
    photo = config.person_photo
    prefix = config.person_prefix.replace("{trigger}", config.trigger_word)
    return photo.template.format(prefix=prefix, outfit=photo.outfits[0], pose=photo.poses[0])


def photo_prompt_for(settings: Settings) -> str:
    return person_photo_prompt(load_config(settings.comfyui_config_file))


def model_sizes(config: ComfyUIConfig, spec: WorkflowConfig | None
                ) -> dict[AspectRatio, tuple[int, int]]:
    return (spec.sizes if spec is not None and spec.sizes else None) or config.sizes


def model_file_problems(config: ComfyUIConfig, workflow: LoadedWorkflow) -> list[str]:
    """Every loader node's file must be the one listed under models (what the user uploads)."""
    files = {entry.file for entry in config.models.get(workflow.name, {}).values()}
    if not files:
        return [f"models.{workflow.name} is not listed in config/comfyui.json"]
    names = [str(node["inputs"][key]) for node in workflow.graph.values()
             for key in ("unet_name", "clip_name", "vae_name")
             if isinstance(node, dict) and key in node.get("inputs", {})]
    return [f"{name} (loader node) is not under models.{workflow.name}" for name in names
            if name not in files]


def build_graph(
    workflow: LoadedWorkflow,
    config: ComfyUIConfig,
    *,
    prompt: str,
    width: int,
    height: int,
    seed: int,
    person: bool,
    lora_strength: float | None = None,
) -> dict[str, Any]:
    """A copy of the workflow with the values set through the mapping."""
    graph = copy.deepcopy(workflow.graph)
    spec, mapping = workflow.spec, workflow.mapping
    values: dict[MappedValue, Any] = {
        "prompt": prompt,
        "negative": spec.negative,
        "seed": seed,
        "width": width,
        "height": height,
        "steps": spec.steps,
        "cfg": spec.cfg,
        "lora_name": spec.lora_name,
        "lora_strength": config.lora_strength if lora_strength is None else lora_strength,
    }
    lora_node = mapping.inputs["lora_name"].node
    for key, value in values.items():
        target = mapping.inputs[key]
        if person or target.node != lora_node:
            graph[target.node]["inputs"][target.input] = value
    if not person:  # no identity: the base model goes straight on, the LoRA node goes
        bypass = mapping.lora_bypass
        graph[bypass.node]["inputs"][bypass.input] = list(bypass.source)
        del graph[lora_node]
    if config.upscale_node.enabled:
        graph[_UPSCALE_LOADER] = {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": config.upscale_node.model},
        }
        graph[_UPSCALE] = {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": [_UPSCALE_LOADER, 0], "image": [mapping.decode, 0]},
        }
        graph[mapping.save]["inputs"]["images"] = [_UPSCALE, 0]
    return graph


def target_size(aspect_ratio: str, long_side: int) -> tuple[int, int]:
    """The delivered size: the long side from IMAGE_DESIGN_SIZE, the exact aspect ratio."""
    width, height = (int(part) for part in aspect_ratio.split(":"))
    if width >= height:
        return long_side, round(long_side * height / width)
    return round(long_side * width / height), long_side


def capabilities_for(config: ComfyUIConfig, model: str) -> ProviderCapabilities:
    spec = config.workflows.get(model)
    seconds = spec.seconds_per_image if spec else max(
        workflow.seconds_per_image for workflow in config.workflows.values()
    )
    price = config.price_per_second_usd
    per_image = round(price * seconds, 6)
    per_request = round(price * (config.cold_start_seconds + config.idle_seconds), 6)
    return ProviderCapabilities(
        max_identity_refs=0,  # the identity is the LoRA
        max_object_refs=0,
        max_style_refs=0,
        max_total_refs=0,
        aspect_ratios=frozenset(model_sizes(config, spec)),
        image_sizes=frozenset(config.target_long_side),
        max_images_per_call=1,
        est_cost_usd_per_image={size: per_image for size in config.target_long_side},
        est_cost_usd_per_request=per_request,
        cost_basis=(
            f"estimate: {config.gpu} at ${price:.6f}/s; {seconds:g} s per image ({model}) + "
            f"{config.cold_start_seconds:g} s cold start + {config.idle_seconds:g} s idle per "
            "request"
        ),
        draws_text=False,
        identity_prompt=config.identity_prompt.replace("{trigger}", config.trigger_word),
        timeout_s=config.timeout_seconds,
        batch_images=True,  # a package's images back-to-back on one warm worker
    )


class ComfyUIImageProvider:
    name = "comfyui"

    def __init__(
        self,
        config: ComfyUIConfig,
        model: str,
        *,
        api_key: str | None,
        endpoint_id: str | None,
        client: RunPodClient | None = None,
    ) -> None:
        self._config = config
        self.capabilities = capabilities_for(config, model)
        self._api_key = api_key
        self._endpoint_id = endpoint_id
        self._client = client

    def generate(self, request: ImageRequest, model: str) -> ImageResult:
        workflow = load_workflow(self._config, model)
        if request.identity_refs or request.object_refs or request.style_refs:
            raise ImageProviderError(
                "ComfyUI workflows take no reference images; the identity is the LoRA."
            )
        if request.person and (
            is_unset(workflow.spec.lora_name) or is_unset(self._config.trigger_word)
        ):
            raise ImageProviderError(
                f"The person's LoRA for {model} is not set yet (loraName and triggerWord in "
                f"config/comfyui.json, Phase 2 Step 4). Nothing was sent. {SWITCH}"
            )
        client = self._client or self._new_client()
        width, height = model_sizes(self._config, workflow.spec)[request.aspect_ratio]
        size = target_size(request.aspect_ratio, self._config.target_long_side[request.image_size])
        prompt, strength = request.prompt, None
        if request.person:  # a clean studio photo; the app composes the post from it
            prompt, strength = person_photo_prompt(self._config), self._config.lora_strength
            (width, height), size = self._config.person_photo.size, self._config.person_photo.size
        images: list[GeneratedImage] = []
        request_ids: list[str] = []
        metrics: dict[str, float] = {
            "modelWidth": width, "modelHeight": height, "delayTimeMs": 0.0, "executionTimeMs": 0.0,
        }
        if request.person:
            metrics["loraStrength"] = strength if strength is not None else 0.0
        cost = 0.0
        for index in range(1, request.count + 1):
            seed = secrets.randbelow(2**32)
            metrics[f"seed{index}"] = seed
            graph = build_graph(
                workflow, self._config, prompt=prompt, width=width, height=height,
                seed=seed, person=request.person, lora_strength=strength,
            )
            label = f"Image {index} of {request.count}"
            try:
                job = client.run(graph)
            except ImageTimeoutError as error:  # billed up to the cancel at most
                error.args = (f"{label}: {error}",)
                error.cost_usd = round(
                    cost + self._config.price_per_second_usd * self._config.timeout_seconds, 6
                )
                raise
            except ImageProviderError as error:
                error.args = (f"{label}: {error}",)
                error.cost_usd = round(cost, 6) or None
                raise
            request_ids.append(job.job_id)
            cost += self._cost(job)
            metrics["delayTimeMs"] += job.delay_ms
            metrics["executionTimeMs"] += job.execution_ms
            if job.status != "COMPLETED":
                raise ImageProviderError(
                    f"{label}: RunPod job {job.job_id} ended {job.status}: "
                    f"{job.error or 'no details'}. {SWITCH}",
                    cost_usd=round(cost, 6),
                )
            try:
                images.append(_image(client, job, size))
            except ImageProviderError as error:
                error.args = (f"{label}: {error}",)
                error.cost_usd = round(cost, 6)
                raise
        return ImageResult(
            images=images,
            provider=self.name,
            model=model,
            provider_request_ids=request_ids,
            cost_usd=round(cost, 6),
            metrics=metrics,
        )

    def _new_client(self) -> RunPodClient:
        if not self._api_key or not self._endpoint_id:
            raise ImageProviderError(
                "RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID must be set in .env to use "
                "IMAGE_PROVIDER=comfyui (see docs/guides/runpod-comfyui.md)."
            )
        return RunPodClient(
            self._api_key,
            self._endpoint_id,
            poll_s=self._config.poll_seconds,
            timeout_s=self._config.timeout_seconds,
        )

    def _cost(self, job: RunPodJob) -> float:
        """GPU seconds from RunPod's times: delay (queue + cold start, so an upper bound) plus
        execution. The idle time after a package's last image is in the estimate only."""
        seconds = (job.delay_ms + job.execution_ms) / 1000
        return self._config.price_per_second_usd * seconds


def _image(client: RunPodClient, job: RunPodJob, size: tuple[int, int]) -> GeneratedImage:
    """The first output image, scaled to the delivered size with Lanczos, as PNG."""
    warnings = f" (worker: {'; '.join(job.warnings)})" if job.warnings else ""
    if not job.images:
        raise ImageProviderError(
            f"RunPod job {job.job_id} finished without an image{warnings}. {SWITCH}"
        )
    item = job.images[0]
    data = item.get("data")
    if not isinstance(data, str) or not data:
        raise ImageProviderError(f"RunPod job {job.job_id} returned an empty image{warnings}.")
    if item.get("type") == "s3_url":
        raw = client.download(data)
    else:
        try:
            raw = base64.b64decode(data.split(",", 1)[-1], validate=True)
        except (binascii.Error, ValueError):
            raise ImageProviderError(
                f"RunPod job {job.job_id} returned image data that is not valid base64."
            ) from None
    try:
        with Image.open(io.BytesIO(raw)) as source:
            image = source.convert("RGB")
    except (OSError, UnidentifiedImageError):
        raise ImageProviderError(
            f"RunPod job {job.job_id} returned data that is not a valid image."
        ) from None
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return GeneratedImage(data=buffer.getvalue(), mime_type="image/png")


def workflow_for(settings: Settings) -> str:
    """The ComfyUI workflow to run: IMAGE_MODEL if it names one, else defaultWorkflow."""
    config = load_config(settings.comfyui_config_file)
    if settings.image_model in config.workflows:
        return settings.image_model
    return config.default_workflow


def create_provider(settings: Settings | None = None) -> ComfyUIImageProvider:
    """Loads config/comfyui.json; the workflow comes from workflow_for (never an OpenRouter
    IMAGE_MODEL)."""
    config = load_config(settings.comfyui_config_file if settings else DEFAULT_CONFIG)
    if settings is None:
        return ComfyUIImageProvider(
            config, config.default_workflow, api_key=None, endpoint_id=None
        )
    key = settings.runpod_api_key.get_secret_value().strip() if settings.runpod_api_key else ""
    return ComfyUIImageProvider(
        config,
        workflow_for(settings),
        api_key=key or None,
        endpoint_id=(settings.runpod_endpoint_id or "").strip() or None,
    )
