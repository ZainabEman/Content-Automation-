"""Non-Roman images made by Codex with its built-in image generation (gpt-image-2, agent adapter).

`ca` cannot call Codex's image tool, so nothing is called here (the pattern of Roman's
Higgsfield jobs, providers/higgsfield_soul.py). A request inside a `ca` command becomes a queued
registry job (the usual idempotency key, unit codex_images) and a job file,
outputs/codex_jobs/<batch>/<job>/job.json: BG ID, the prompt, the reference image paths (the ones
OpenRouter would get), the size to generate (config/codex_image.json), the final canvas, the
output path and status awaiting_external; batch.json lists the batch's jobs (at most
max_images_per_batch). Codex makes each image once (skill generate-images-codex), saves it to the
output path and runs `ca image import`, which checks the file, marks the job done and continues
the build: this adapter then crops the image to the requested aspect and the app draws and checks
the design. $0 per image; the authorization caps the count. No fallback to another provider: a
missing image keeps its item pending.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from content_automation.ai.image import (
    ALL_ASPECT_RATIOS,
    IMAGE_SIZES,
    GeneratedImage,
    ImageAwaitingAgent,
    ImageRequest,
    ImageRequestError,
    ImageResult,
    ProviderCapabilities,
)
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text

CONFIG_FILE = Path("config/codex_image.json")
JOB_FILE = "job.json"
BATCH_FILE = "batch.json"
OUTPUT_NAME = "image.png"
AWAITING = "awaiting_external"
DONE = "done"
UNIT = "codex_images"
_PROJECT_ROOT = Path(__file__).resolve().parents[5]
_LOCK = threading.Lock()  # a parallel build writes jobs from several threads
_OPEN_BATCH: dict[Path, Path] = {}  # this process's open batch per jobs root


def load_config(path: Path = CONFIG_FILE) -> dict[str, Any]:
    found = path if path.is_file() else _PROJECT_ROOT / path
    data = json.loads(found.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ImageRequestError(f"{path} must be a JSON object")
    return data


def generate_size(aspect: str, config: dict[str, Any] | None = None) -> str:
    sizes = dict((config or load_config())["sizes"])
    if aspect not in sizes:
        raise ImageRequestError(f"config/codex_image.json has no size for {aspect} "
                                f"({', '.join(sizes)})")
    return str(sizes[aspect])


def request_key(request: ImageRequest) -> str:
    """What makes two requests the same picture (the job file is found by it again)."""
    refs = [str(ref.path) for ref in
            (*request.identity_refs, *request.object_refs, *request.style_refs)]
    text = json.dumps([request.prompt, request.aspect_ratio, request.image_size, refs])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class CodexJob:
    """One image for Codex (outputs/codex_jobs/<batch>/<job>/job.json)."""

    folder: Path
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return self.folder / JOB_FILE

    @property
    def output(self) -> Path:
        return Path(str(self.data["output_path"]))

    @property
    def batch(self) -> str:
        return self.folder.parent.name

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(self.data, indent=2, ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: Path) -> CodexJob:
        return cls(path.parent, json.loads(path.read_text(encoding="utf-8")))


def all_jobs(root: Path, batch: str | None = None) -> list[CodexJob]:
    pattern = f"{batch}/*/{JOB_FILE}" if batch else f"*/*/{JOB_FILE}"
    return [CodexJob.load(path) for path in sorted(root.glob(pattern))]


def _batch_folder(root: Path, limit: int) -> Path:
    """This run's open batch while it has room, else a new one (B-<UTC stamp>[-n])."""
    current = _OPEN_BATCH.get(root)
    if current is not None and len(list(current.glob(f"*/{JOB_FILE}"))) < limit:
        return current
    stamp = datetime.now(UTC).strftime("B-%Y%m%d-%H%M%S")
    folder, number = root / stamp, 1
    while folder.exists():
        number += 1
        folder = root / f"{stamp}-{number}"
    folder.mkdir(parents=True)
    _OPEN_BATCH[root] = folder
    return folder


def _write_batch(folder: Path, limit: int) -> None:
    jobs = [CodexJob.load(path) for path in sorted(folder.glob(f"*/{JOB_FILE}"))]
    path = folder / BATCH_FILE
    created = (json.loads(path.read_text(encoding="utf-8")).get("createdAt")
               if path.is_file() else None) or _now()
    status = DONE if jobs and all(job.data["status"] == DONE for job in jobs) else AWAITING
    atomic_write_text(path, json.dumps({
        "batch": folder.name, "status": status, "createdAt": created, "updatedAt": _now(),
        "maxImages": limit,
        "jobs": [{"job": job.folder.name, "bgId": job.data.get("bg_id"),
                  "status": job.data["status"], "output_path": job.data["output_path"]}
                 for job in jobs],
        "next": "generate-images-codex skill, then: uv run ca image import " + folder.name,
    }, indent=2, ensure_ascii=False) + "\n")


@dataclass
class Imported:
    """`ca image import`: what was imported, what is still missing, the packages to build."""

    imported: list[CodexJob] = field(default_factory=list)
    missing: list[CodexJob] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    packages: list[Path] = field(default_factory=list)


def import_images(root: Path, batch: str | None = None, *, keys: set[str] | None = None
                  ) -> Imported:
    """Check each awaiting job's file (it exists and is an image), mark it done; a done job no
    build has used yet (an earlier import) names its package again, so a resume continues it.
    keys: only these registry idempotency keys (`ca jobs resume`). Nothing is generated."""
    config = load_config()
    found = Imported()
    if batch is not None and not (root / batch).is_dir():
        raise ImageRequestError(f"no Codex batch {batch} in {root}")
    touched: set[Path] = set()
    for job in all_jobs(root, batch):
        if keys is not None and job.data.get("idempotency_key") not in keys:
            continue
        if job.data["status"] == AWAITING:
            output = job.output
            if not output.is_file():
                found.missing.append(job)
                continue
            try:
                with Image.open(output) as opened:
                    opened.verify()
                with Image.open(output) as opened:
                    size = opened.size
            except (OSError, SyntaxError) as error:
                found.problems.append(f"{job.batch}/{job.folder.name}: {output} is not an image "
                                      f"({error}); the item stays pending")
                continue
            job.data.update(status=DONE, imported_at=_now(), image_size=f"{size[0]}x{size[1]}")
            job.save()
            touched.add(job.folder.parent)
            found.imported.append(job)
        package = job.data.get("package")
        unused = job.data["status"] == DONE and not job.data.get("used_at")
        if unused and package and Path(package) not in found.packages:
            found.packages.append(Path(package))
    for folder in touched:
        _write_batch(folder, int(config["max_images_per_batch"]))
    return found


class CodexBuiltinProvider:
    name = "codex_builtin"
    mode = "agent"

    def __init__(self, settings: Settings | None) -> None:
        self.settings = settings
        self.config = load_config()
        aspects = frozenset(aspect for aspect in ALL_ASPECT_RATIOS if aspect in
                            self.config["sizes"])
        refs = int(self.config.get("max_reference_images", 10))
        self.capabilities = ProviderCapabilities(
            max_identity_refs=0, max_object_refs=refs, max_style_refs=refs, max_total_refs=refs,
            aspect_ratios=aspects, image_sizes=frozenset(IMAGE_SIZES), max_count=1,
            est_cost_usd_per_image={size: 0.0 for size in IMAGE_SIZES}, draws_text=False,
            cost_basis=(f"{self.config['tool']} ({self.config['model']}): $0 per image; the "
                        f"authorization counts the images ({UNIT})"))

    @property
    def model(self) -> str:
        return str(self.config["model"])

    def root(self) -> Path:
        base = self.settings.packages_dir if self.settings is not None else Path("outputs")
        return base / str(self.config["jobs_dir"])

    def find(self, request: ImageRequest) -> CodexJob | None:
        """The newest job of this request (a done one first)."""
        key = request_key(request)
        matches = [job for job in all_jobs(self.root()) if job.data.get("request_key") == key]
        done = [job for job in matches if job.data["status"] == DONE]
        chosen = done or matches
        return max(chosen, key=lambda job: str(job.data.get("created_at", ""))) if chosen else None

    def delivered(self, request: ImageRequest) -> Path | None:
        job = self.find(request)
        if job is None or job.data["status"] != DONE or not job.output.is_file():
            return None
        return job.output

    def queue(self, request: ImageRequest, *, idempotency_key: str,
              meta: dict[str, Any]) -> Path:
        """The job file of this registry job (written once; an existing one is returned)."""
        with _LOCK:
            for job in all_jobs(self.root()):
                if job.data.get("idempotency_key") == idempotency_key:
                    return job.path
            limit = int(self.config["max_images_per_batch"])
            batch = _batch_folder(self.root(), limit)
            bg_id = meta.get("bg_id") or "direct"
            folder = batch / f"{bg_id}_{idempotency_key[:12]}"
            refs = [{"role": role, "asset_id": ref.asset_id, "path": str(ref.path.resolve())}
                    for role, group in (("identity", request.identity_refs),
                                        ("object", request.object_refs),
                                        ("style", request.style_refs))
                    for ref in group]
            job = CodexJob(folder, {
                "provider": self.name, "model": self.model, "tool": self.config["tool"],
                "status": AWAITING, "bg_id": meta.get("bg_id"),
                "package": meta.get("package"), "registry_job_id": meta.get("registry_job_id"),
                "idempotency_key": idempotency_key, "request_key": request_key(request),
                "prompt": request.prompt, "reference_images": refs,
                "aspect_ratio": request.aspect_ratio,
                "generate_size": generate_size(request.aspect_ratio, self.config),
                "final_canvas": request.options.get("canvas") or request.aspect_ratio,
                "output_path": str((folder / OUTPUT_NAME).resolve()),
                "rules": ["one image, generated once", "no text, letters, numbers, logos or "
                          "watermarks in the image", "save as PNG to output_path"],
                "created_at": _now(),
            })
            job.save()
            _write_batch(batch, limit)
            return job.path

    def generate(self, request: ImageRequest, model: str) -> ImageResult:
        del model  # Codex's built-in model (config/codex_image.json)
        job = self.find(request)
        if job is None or job.data["status"] != DONE or not job.output.is_file():
            path = job.path if job is not None else self.root()
            raise ImageAwaitingAgent(f"waiting for Codex: image job {path}", path)
        with Image.open(job.output) as opened:
            image = opened.convert("RGB")
        job.data["used_at"] = _now()  # the build has it now; an import does not repeat it
        job.save()
        left, _, right = request.aspect_ratio.partition(":")
        width, height = image.size  # the app crops the generated size to the aspect
        target = int(left) / int(right)
        if abs(width / height - target) > 0.01:
            size = ((width, round(width / target)) if width / height < target else
                    (round(height * target), height))
            image = ImageOps.fit(image, size, Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return ImageResult(
            images=[GeneratedImage(data=buffer.getvalue(), mime_type="image/png")],
            provider=self.name, model=self.model,
            provider_request_ids=[f"codex-{job.batch}/{job.folder.name}"], cost_usd=0.0,
            metrics={"generatedWidth": float(width), "generatedHeight": float(height)})


def create_provider(settings: Settings | None = None) -> CodexBuiltinProvider:
    return CodexBuiltinProvider(settings)


__all__ = ["AWAITING", "DONE", "UNIT", "CodexBuiltinProvider", "CodexJob", "Imported",
           "all_jobs", "create_provider", "generate_size", "import_images", "load_config",
           "request_key"]
