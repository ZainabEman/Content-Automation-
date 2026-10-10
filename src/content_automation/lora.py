"""The person's LoRA for ComfyUI: dataset, AI Toolkit training config, trained file.

Training runs on a temporary RunPod Pod with Ostris AI Toolkit (MIT), writing to the network
volume the Serverless endpoint reads: a Pod mounts it at /workspace, Serverless at
/runpod-volume, so a LoRA copied to /workspace/models/loras/ is read by the worker from
/runpod-volume/models/loras/. Everything here is local and free; nothing calls RunPod.

- prepare: refused without CONSENT.md (name, date, scope: training + cloud upload) in the
  identity folder. Photos from the folder and its extra/ subfolder: one face (OpenCV Haar
  frontal + profile), at least minSide px, no duplicates (perceptual hash). Fewer than
  minPhotos is refused, fewer than recommendedPhotos warned. Each photo is turned upright,
  stripped of EXIF, scaled to trainSide on the short side (never up) and captioned
  "<trigger>, <setting/outfit>" (captions.json, else defaultCaption). Output: an AI Toolkit
  dataset (images + same-name .txt) zipped to outputs/lora/dataset_<date>.zip.
- training_config: an AI Toolkit YAML from the example defaults (no tuning) + the estimate.
- set_lora: points config/comfyui.json at the trained file, so person images are allowed.
"""

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ConfigDict, Field, ValidationError

from content_automation.ai.image import ImageError
from content_automation.ai.image.providers.comfyui import ComfyUIConfig, is_unset, load_config
from content_automation.core.config import Settings
from content_automation.core.files import CamelModel, atomic_write_text

ModelKey = Literal["qwen", "zimage"]
OUT_DIR = Path("outputs/lora")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
_DETECT_SIDE = 1024  # faces are searched on a copy scaled to this long side
_MIN_FACE = 0.08  # smallest face side, share of the image's short side
_SMALL_FACE = 0.25  # faces under this share of the largest one are ignored (background)
_CONSENT_TEMPLATE = (
    "Name: <full name of the person in the photos>\n"
    "Date: <YYYY-MM-DD>\n"
    "Scope: training a LoRA on these photos and uploading them to cloud GPU services (RunPod)\n"
)
_SAMPLE_PROMPTS = (
    "[trigger], a man in a navy suit in a modern office, photorealistic portrait, window light",
    "[trigger], a man smiling at a cafe table with a laptop, natural light, photo",
    "[trigger], close-up portrait of a man, neutral grey background, studio light",
    "[trigger], a man presenting in front of a screen in a meeting room, photo",
    "a man in a navy suit in a modern office, photorealistic portrait, window light",
)


class LoraError(ValueError):
    """The LoRA step cannot go on; the message says what to fix."""


class _Model(CamelModel):
    model_config = ConfigDict(extra="forbid")


class PodSpec(_Model):
    gpu: str = Field(min_length=1)
    price_per_hour_usd: float = Field(gt=0)
    price_source: str = ""
    setup_hours: float = Field(ge=0)  # start, model download, copying the result
    pod_volume: str = "/workspace"
    serverless_volume: str = "/runpod-volume"
    datasets: str = "lora/datasets"
    output: str = "lora/output"
    loras: str = "models/loras"


class TrainSpec(_Model):
    workflow: str = Field(min_length=1)  # the config/comfyui.json workflow it is for
    arch: str = Field(min_length=1)
    name_or_path: str = Field(min_length=1)
    assistant_lora_path: str = ""
    quantize: str = ""  # "" = none, else the qtype (e.g. qfloat8)
    steps: int = Field(ge=1)
    rank: int = Field(ge=1)
    lr: float = Field(gt=0)
    training_hours: float = Field(gt=0)  # estimate, for the cost
    sample_guidance: float = Field(gt=0)
    sample_steps: int = Field(ge=1)
    source: str = ""


class LoraConfig(_Model):
    identity_set: str = Field(min_length=1)
    extra_folder: str = "extra"
    consent_file: str = "CONSENT.md"
    captions_file: str = "captions.json"
    default_caption: str = Field(min_length=1)
    min_photos: int = Field(ge=1)
    recommended_photos: int = Field(ge=1)
    min_side: int = Field(ge=256)
    train_side: int = Field(ge=256)
    duplicate_distance: int = Field(ge=0, le=64)
    pod: PodSpec
    models: dict[ModelKey, TrainSpec]


def load_lora_config(path: Path) -> LoraConfig:
    file = path if path.is_absolute() or path.exists() else _PROJECT_ROOT / path
    try:
        return LoraConfig.model_validate_json(file.read_text(encoding="utf-8"))
    except OSError:
        raise LoraError(f"LoRA config not found: {path}. Restore config/lora.json.") from None
    except ValidationError as error:
        problems = sorted({
            ".".join(str(part) for part in issue["loc"]) for issue in error.errors()
        })
        raise LoraError(f"{file.name} is invalid; check: {'; '.join(problems)}.") from None


def _comfyui(settings: Settings) -> ComfyUIConfig:
    try:
        return load_config(settings.comfyui_config_file)
    except ImageError as error:
        raise LoraError(str(error)) from None


def _trigger(comfyui: ComfyUIConfig) -> str:
    if is_unset(comfyui.trigger_word) or not re.fullmatch(r"[A-Za-z0-9_]+", comfyui.trigger_word):
        raise LoraError(
            'Set "triggerWord" in config/comfyui.json to one rare token of letters, digits and '
            '"_" (e.g. r0man_bg); it names the person in captions and prompts.'
        )
    return comfyui.trigger_word


# --- Consent ---------------------------------------------------------------------------------


def check_consent(folder: Path, name: str) -> str:
    """CONSENT.md must name the person, a date and a scope covering training + cloud upload."""
    path = folder / name
    template = f"Create {path} with:\n{_CONSENT_TEMPLATE}"
    if not path.is_file():
        raise LoraError(f"Refused: no written consent on file. {template}")
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, colon, value = line.partition(":")
        if colon:
            fields[key.strip().strip("*#- ").casefold()] = value.strip()
    problems = []
    if is_unset(fields.get("name", "")):
        problems.append("Name")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fields.get("date", "")):
        problems.append("Date (YYYY-MM-DD)")
    scope = fields.get("scope", "").casefold()
    if "training" not in scope or "upload" not in scope:
        problems.append("Scope (must cover training and cloud upload)")
    if problems:
        raise LoraError(f"Refused: {path.name} is missing {', '.join(problems)}. {template}")
    return f"Consent: {fields['name']}, {fields['date']} ({path})"


# --- Photo checks ----------------------------------------------------------------------------


@dataclass
class Photo:
    source: Path
    label: str  # relative to the identity folder, e.g. 3.jpg or extra/a.jpg
    image: Image.Image
    problem: str | None = None
    note: str | None = None


def _photos(folder: Path, extra: str) -> list[Path]:
    found = []
    for where in (folder, folder / extra):
        if where.is_dir():
            found += sorted(
                (path for path in where.iterdir()
                 if path.is_file() and path.suffix.lower() in _PHOTO_SUFFIXES),
                key=lambda path: [int(part) if part.isdigit() else part
                                  for part in re.split(r"(\d+)", path.stem.casefold())],
            )
    return found


def _dhash(image: Image.Image) -> int:
    small = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    bits = 0
    for row in range(8):
        for column in range(8):
            left, right = pixels[row * 9 + column], pixels[row * 9 + column + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


_CASCADES: dict[str, cv2.CascadeClassifier] = {}


def _cascade(name: str) -> cv2.CascadeClassifier:
    if name not in _CASCADES:  # the cascades ship in cv2/data (OpenCV 4.x)
        path = Path(cv2.__file__).parent / "data" / name
        _CASCADES[name] = cv2.CascadeClassifier(str(path))
    return _CASCADES[name]


def count_faces(image: Image.Image) -> int:
    """Faces in the photo: frontal, else profile (both sides); overlapping and tiny
    background boxes are not counted."""
    scale = min(1.0, _DETECT_SIDE / max(image.size))
    small = image.convert("L").resize(
        (round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS
    )
    gray = np.asarray(small)
    side = round(min(gray.shape) * _MIN_FACE)
    boxes: list[tuple[int, int, int, int]] = []
    for name, flip in (
        ("haarcascade_frontalface_default.xml", False),
        ("haarcascade_profileface.xml", False),
        ("haarcascade_profileface.xml", True),
    ):
        source = np.ascontiguousarray(gray[:, ::-1]) if flip else gray
        found = _cascade(name).detectMultiScale(
            source, scaleFactor=1.1, minNeighbors=6, minSize=(side, side)
        )
        boxes += [(int(x), int(y), int(w), int(h)) for x, y, w, h in found]
        if boxes:
            break
    if not boxes:
        return 0
    largest = max(w for _, _, w, _ in boxes)
    kept: list[tuple[int, int, int, int]] = []
    for box in sorted(boxes, key=lambda b: -b[2]):
        x, y, w, h = box
        if w < largest * _SMALL_FACE:
            continue
        center = (x + w / 2, y + h / 2)
        if any(kx <= center[0] <= kx + kw and ky <= center[1] <= ky + kh
               for kx, ky, kw, kh in kept):
            continue
        kept.append(box)
    return len(kept)


def _check_photos(
    paths: list[Path], folder: Path, config: LoraConfig, keep: set[str]
) -> list[Photo]:
    photos: list[Photo] = []
    exact: dict[str, str] = {}
    hashes: list[tuple[int, str]] = []
    for path in paths:
        label = path.relative_to(folder).as_posix()
        try:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, UnidentifiedImageError):
            photos.append(Photo(path, label, Image.new("RGB", (1, 1)), problem="unreadable"))
            continue
        photo = Photo(path, label, image)
        photos.append(photo)
        if min(image.size) < config.min_side:
            photo.problem = (
                f"too small ({image.width}x{image.height}; needs {config.min_side} px on the "
                "short side)"
            )
            continue
        if digest in exact:
            photo.problem = f"the same file as {exact[digest]}"
            continue
        exact[digest] = label
        value = _dhash(image)
        twin = next(
            (other for known, other in hashes
             if (value ^ known).bit_count() <= config.duplicate_distance),
            None,
        )
        if twin is not None:
            photo.problem = f"near-duplicate of {twin}"
            continue
        hashes.append((value, label))
        faces = count_faces(image)
        if faces != 1 and label in keep:
            photo.note = f"{faces} faces detected; kept by --keep (checked by eye)"
        elif faces == 0:
            photo.problem = "no face found (if it is clearly visible, add --keep " + label + ")"
        elif faces > 1:
            photo.problem = f"{faces} faces: only the person may be in the photo"
    return photos


def _captions(folder: Path, name: str) -> dict[str, str]:
    path = folder / name
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise LoraError(
            f'{path} is not valid JSON: use {{"3.jpg": "navy suit, office"}}.'
        ) from None
    if not isinstance(data, dict):
        raise LoraError(f"{path} must map file names to short descriptions.")
    return {str(key): " ".join(str(value).split()) for key, value in data.items() if value}


@dataclass
class PrepareResult:
    lines: list[str] = field(default_factory=list)
    archive: Path | None = None


def prepare_dataset(
    settings: Settings, *, keep: list[str] | None = None, out_dir: Path = OUT_DIR
) -> PrepareResult:
    """Check consent and photos, then write the AI Toolkit dataset zip (local, free)."""
    config = load_lora_config(settings.lora_config_file)
    trigger = _trigger(_comfyui(settings))
    folder = settings.references_dir / config.identity_set
    if not folder.is_dir():
        raise LoraError(f"Identity folder not found: {folder}.")
    result = PrepareResult([check_consent(folder, config.consent_file)])
    paths = _photos(folder, config.extra_folder)
    photos = _check_photos(paths, folder, config, set(keep or []))
    accepted = [photo for photo in photos if photo.problem is None]
    for photo in photos:
        state = "ok" if photo.problem is None else f"left out: {photo.problem}"
        note = f" ({photo.note})" if photo.note else ""
        result.lines.append(f"  {photo.label}: {state}{note}")
    count = len(accepted)
    if count < config.min_photos:
        raise LoraError(
            "\n".join(result.lines) + f"\nRefused: {count} usable photos; at least "
            f"{config.min_photos} are needed (add more to {folder / config.extra_folder})."
        )
    if count < config.recommended_photos:
        result.lines.append(
            f"WARNING: {count} usable photos; {config.recommended_photos}+ give a more reliable "
            f"likeness (varied angles, light and outfits in {folder / config.extra_folder})."
        )
    captions = _captions(folder, config.captions_file)
    missing = [photo.label for photo in accepted if photo.label not in captions]
    if missing:
        result.lines.append(
            f'Captions: "{trigger}, {config.default_caption}" for {", ".join(missing)} (add '
            f'short setting/outfit notes to {folder / config.captions_file}, e.g. '
            '{"3.jpg": "navy suit, office"}).'
        )
    name = f"dataset_{date.today():%Y-%m-%d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"{name}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for number, photo in enumerate(accepted, start=1):
            image = photo.image
            short = min(image.size)
            if short > config.train_side:  # never upscaled
                ratio = config.train_side / short
                image = image.resize(
                    (round(image.width * ratio), round(image.height * ratio)),
                    Image.Resampling.LANCZOS,
                )
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=95)  # no EXIF: no location data
            stem = f"{name}/{number:02d}"
            bundle.writestr(f"{stem}.jpg", buffer.getvalue())
            caption = captions.get(photo.label, config.default_caption)
            bundle.writestr(f"{stem}.txt", f"{trigger}, {caption}\n")
    result.archive = archive
    result.lines.append(
        f"Dataset: {archive.resolve()} ({count} photos + captions, trigger {trigger}). It holds "
        "the person's photos: upload it only to the RunPod Pod, never elsewhere."
    )
    return result


# --- AI Toolkit config -----------------------------------------------------------------------


def _q(value: object) -> str:
    """A YAML scalar: JSON strings, numbers and booleans are valid YAML."""
    return json.dumps(value)


def newest_dataset(out_dir: Path = OUT_DIR) -> Path:
    found = sorted(out_dir.glob("dataset_*.zip"))
    if not found:
        raise LoraError("No dataset yet: run `uv run ca lora prepare` first.")
    return found[-1]


def training_config(
    settings: Settings, model: ModelKey, dataset: Path, *, out_dir: Path = OUT_DIR
) -> tuple[Path, list[str]]:
    """Write the AI Toolkit YAML for one model; returns its path and the lines to show."""
    config = load_lora_config(settings.lora_config_file)
    comfyui = _comfyui(settings)
    trigger = _trigger(comfyui)
    spec = config.models[model]
    if spec.workflow not in comfyui.workflows:
        raise LoraError(
            f"config/lora.json {model}.workflow {spec.workflow} is not in comfyui.json."
        )
    pod = config.pod
    job = f"{trigger}_{spec.workflow}"
    dataset_dir = f"{pod.pod_volume}/{pod.datasets}/{dataset.stem}"
    output_dir = f"{pod.pod_volume}/{pod.output}"
    model_lines = [
        f"        name_or_path: {_q(spec.name_or_path)}",
        f"        arch: {_q(spec.arch)}",
    ]
    if spec.assistant_lora_path:
        model_lines.append(f"        assistant_lora_path: {_q(spec.assistant_lora_path)}")
    if spec.quantize:
        model_lines += [
            "        quantize: true",
            f"        qtype: {_q(spec.quantize)}",
            "        quantize_te: true",
            f"        qtype_te: {_q(spec.quantize)}",
        ]
    else:
        model_lines.append("        quantize: false")
    model_lines.append("        low_vram: false")
    prompts = [f"          - {_q(prompt)}" for prompt in _SAMPLE_PROMPTS]
    yaml = "\n".join([
        f"# AI Toolkit LoRA config for {spec.workflow}, written by `ca lora config`.",
        f"# Defaults: {spec.source}.",
        f"# Run on the Pod: python run.py {pod.pod_volume}/lora/{job}.yaml",
        "job: extension",
        "config:",
        f"  name: {_q(job)}",
        "  process:",
        "    - type: \"sd_trainer\"",
        f"      training_folder: {_q(output_dir)}",
        "      device: \"cuda:0\"",
        f"      trigger_word: {_q(trigger)}",
        "      network:",
        "        type: \"lora\"",
        f"        linear: {spec.rank}",
        f"        linear_alpha: {spec.rank}",
        "      save:",
        "        dtype: \"float16\"",
        "        save_every: 250",
        "        max_step_saves_to_keep: 4",
        "      datasets:",
        f"        - folder_path: {_q(dataset_dir)}",
        "          caption_ext: \"txt\"",
        "          caption_dropout_rate: 0.05",
        "          cache_latents_to_disk: true",
        "          resolution: [512, 768, 1024]",
        "      train:",
        "        batch_size: 1",
        "        cache_text_embeddings: true",
        f"        steps: {spec.steps}",
        "        gradient_accumulation: 1",
        "        train_unet: true",
        "        train_text_encoder: false",
        "        gradient_checkpointing: true",
        "        noise_scheduler: \"flowmatch\"",
        "        optimizer: \"adamw8bit\"",
        f"        lr: {spec.lr}",
        "        dtype: \"bf16\"",
        "      model:",
        *model_lines,
        "      sample:",
        "        sampler: \"flowmatch\"",
        "        sample_every: 250",
        "        width: 1024",
        "        height: 1024",
        "        prompts:",
        *prompts,
        "        neg: \"\"",
        "        seed: 42",
        "        walk_seed: true",
        f"        guidance_scale: {spec.sample_guidance}",
        f"        sample_steps: {spec.sample_steps}",
        "meta:",
        "  name: \"[name]\"",
        "  version: \"1.0\"",
        "",
    ])
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{job}.yaml"
    atomic_write_text(path, yaml)
    hours = spec.training_hours + pod.setup_hours
    cost = pod.price_per_hour_usd * hours
    trained = f"{output_dir}/{job}/{job}.safetensors"
    lines = [
        f"Config: {path.resolve()}",
        f"  dataset on the Pod: {dataset_dir} (unzip {dataset.name} into "
        f"{pod.pod_volume}/{pod.datasets}/)",
        f"  trained file: {trained}",
        f"  copy it to: {pod.pod_volume}/{pod.loras}/{job}.safetensors (the worker reads "
        f"{pod.serverless_volume}/{pod.loras}/)",
        f"  then: uv run ca lora set {model} {job}.safetensors",
        f"Estimate (not a quote): {pod.gpu} at ${pod.price_per_hour_usd:.2f}/h x {hours:g} h "
        f"({spec.training_hours:g} h training + {pod.setup_hours:g} h setup) = ${cost:.2f}. "
        "Billing runs until the Pod is terminated.",
        f"  Unconfirmed settings: {spec.source}.",
    ]
    return path, lines


# --- The trained file ------------------------------------------------------------------------


def set_lora(settings: Settings, model: ModelKey, filename: str) -> list[str]:
    """Point the model's ComfyUI workflow at the trained LoRA file (in models/loras)."""
    config = load_lora_config(settings.lora_config_file)
    name = filename.strip()
    if not name.endswith(".safetensors") or re.search(r"[\\/]|\.\.", name):
        raise LoraError(
            "Give the file name only, as it lies in models/loras/ on the volume, e.g. "
            "r0man_bg_qwen_image_2512.safetensors."
        )
    workflow = config.models[model].workflow
    file = settings.comfyui_config_file
    path = file if file.is_absolute() or file.exists() else _PROJECT_ROOT / file
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        data["workflows"][workflow]["loraName"] = name
    except (KeyError, TypeError):
        raise LoraError(f"config/comfyui.json has no workflow {workflow}.") from None
    try:
        checked = ComfyUIConfig.model_validate(data)
    except ValidationError as error:
        raise LoraError(
            f"config/comfyui.json would be invalid: {error.error_count()} problem(s)."
        ) from None
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    lines = [f"{workflow}: loraName = {name} ({path})"]
    if is_unset(checked.trigger_word):
        lines.append("WARNING: triggerWord is still a placeholder; person images stay refused.")
    pod = config.pod
    lines.append(
        f"The worker must find {pod.serverless_volume}/{pod.loras}/{name} (worker 5.11.0 names "
        "missing files before running). Next: a dry run, then the Step 5 comparison."
    )
    return lines
