"""Roman's images: Codex makes them with the Higgsfield plugin, model Soul 2.0 (agent adapter).

`ca` and Claude Code cannot call Codex plugins, so nothing is called here. A request becomes a
job file, outputs/_system/higgsfield/<key>/job.json (the prompt that opens with the saved
character's token, the character name, model Soul 2.0, the aspect ratio to generate (validated
against the Soul 2.0 list in config/roman_image_guidelines.json), one image, the expected output
path, the credit estimate and numbered instructions), and the job waits (ImageAwaitingAgent):
nothing is charged before an image exists. Codex makes the image, saves it to the expected path
and runs `ca higgsfield record <key> --file … --credits …` (or `ca higgsfield fail`), then the
package build again. Then this adapter returns the image: the person-zone check first (Roman in
the outer quarter on the planned side, nothing person-like in the empty two-thirds); a failure
rejects that attempt and asks for one more (at most maxAttempts, every attempt's credits
counted); then the person-safe crop to the canvas aspect (3:4 to 4:5 for Facebook). No fallback
to another provider: two failed attempts fail the job with the reasons. """

from __future__ import annotations

import hashlib
import io
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from content_automation.ai.image import (
    ALL_ASPECT_RATIOS,
    IMAGE_SIZES,
    GeneratedImage,
    ImageAwaitingAgent,
    ImageProviderError,
    ImageRequest,
    ImageRequestError,
    ImageResult,
    ProviderCapabilities,
)
from content_automation.content.roman_prompt import CONFIG_FILE, load_guidelines
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.core.person_zone import CropError, detect, safe_crop

GUIDELINES = CONFIG_FILE  # config/roman_image_guidelines.json
JOB_FILE = "job.json"


def guidelines() -> dict[str, Any]:
    return load_guidelines()


def _ratio(aspect: str) -> tuple[int, int]:
    left, _, right = aspect.partition(":")
    return int(left), int(right)


def generation_aspect(target: str, config: dict[str, Any] | None = None) -> str:
    """The Soul 2.0 aspect for a canvas aspect: the mapping, else the nearest supported one."""
    data = config or guidelines()
    supported = list(data["higgsfield"]["aspectRatios"])
    mapped = data.get("canvasAspects", {}).get(target)
    if mapped:
        if mapped not in supported:
            raise ImageRequestError(f"canvasAspects maps {target} to {mapped}, which Soul 2.0 "
                                    f"does not support ({', '.join(supported)})")
        return str(mapped)
    width, height = _ratio(target)
    nearest: str = min(supported, key=lambda value: abs(
        _ratio(value)[0] / _ratio(value)[1] - width / height))
    return nearest


def zone_problems(zone_image: Image.Image, side: str, share: float) -> list[str]:
    """Roman in the outer `share` of the width on his side; nothing person-like elsewhere."""
    zone = detect(zone_image)
    width = zone_image.size[0]
    if not zone.found or zone.box is None:
        return ["no person found (expected Roman at the "
                f"{'right' if side == 'S-R' else 'left'} edge)"]
    left, _, right, _ = zone.box
    problems = []
    if side == "S-R" and left < width * (1 - share):
        problems.append(f"Roman reaches {left / width:.0%} from the left; he must stay in the "
                        f"rightmost {share:.0%}")
    if side == "S-L" and right > width * share:
        problems.append(f"Roman reaches {right / width:.0%} of the width; he must stay in the "
                        f"leftmost {share:.0%}")
    empty = (0, int(width * 2 / 3)) if side == "S-R" else (int(width / 3), width)
    strays = [box for box in zone.regions
              if empty[0] <= (box[0] + box[2]) / 2 <= empty[1]]
    if strays:
        problems.append(f"{len(strays)} person-like region(s) in the empty two-thirds")
    return problems


class HiggsfieldJob:
    """One Roman image request on disk (outputs/_system/higgsfield/<key>/job.json)."""

    def __init__(self, folder: Path, data: dict[str, Any]) -> None:
        self.folder = folder
        self.data = data

    @classmethod
    def for_request(cls, request: ImageRequest, root: Path) -> HiggsfieldJob:
        config = guidelines()
        higgsfield = config["higgsfield"]
        aspect = generation_aspect(request.aspect_ratio, config)
        if aspect not in higgsfield["aspectRatios"]:
            raise ImageRequestError(f"{aspect} is not a Soul 2.0 aspect ratio")
        key = hashlib.sha256(f"{request.prompt}|{request.aspect_ratio}|"
                             f"{request.options.get('combination', '')}".encode()).hexdigest()[:12]
        folder = root / key
        path = folder / JOB_FILE
        if path.is_file():
            return cls(folder, json.loads(path.read_text(encoding="utf-8")))
        credits = float(higgsfield["estimatedCreditsPerImage"])
        data = {
            "key": key, "status": "pending", "prompt": request.prompt,
            "characterName": higgsfield["characterName"],
            "characterToken": str(higgsfield["characterToken"]).format(
                name=higgsfield["characterName"]),
            "model": higgsfield["model"], "plugin": higgsfield["plugin"],
            "aspectRatio": aspect, "targetAspect": request.aspect_ratio,
            "cropToTarget": aspect != request.aspect_ratio, "images": 1,
            "combination": request.options.get("combination", ""),
            "side": request.options.get("side", "S-R"),
            "maxAttempts": int(higgsfield["maxAttempts"]),
            "estimate": {"creditsPerImage": credits, "usdPerCredit": higgsfield["usdPerCredit"],
                         "note": higgsfield["estimateNote"]},
            "attempts": [], "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        job = cls(folder, data)
        job.new_attempt()
        return job

    @property
    def path(self) -> Path:
        return self.folder / JOB_FILE

    @property
    def attempt(self) -> dict[str, Any]:
        attempts: list[dict[str, Any]] = self.data["attempts"]
        return attempts[-1]

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(self.data, indent=2, ensure_ascii=False) + "\n")

    def credits(self) -> float:
        return sum(float(item.get("credits") or 0) for item in self.data["attempts"])

    def new_attempt(self) -> None:
        number = len(self.data["attempts"]) + 1
        expected = (self.folder / f"attempt-{number}.png").resolve()
        self.data["attempts"].append({"n": number, "status": "pending",
                                      "expectedOutput": str(expected), "credits": None})
        self.data["status"] = "pending"
        self.data["expectedOutput"] = str(expected)
        self.data["instructions"] = instructions(self)
        self.save()

    def reject(self, reason: str) -> bool:
        """Reject the current attempt; True when another one is allowed (and requested)."""
        current = self.attempt
        current.update(status="rejected", reason=reason)
        if len(self.data["attempts"]) < int(self.data["maxAttempts"]):
            self.new_attempt()
            return True
        self.data["status"] = "failed"
        self.save()
        return False

    def delivered(self) -> Path | None:
        current = self.attempt
        if current.get("status") != "delivered":
            return None
        path = Path(str(current["expectedOutput"]))
        return path if path.is_file() else None


def instructions(job: HiggsfieldJob) -> list[str]:
    data = job.data
    key = data["key"]
    return [
        f"1. Use the {data['plugin']} plugin in Codex: find its image generation tool among the "
        "plugin's tools now (do not assume a tool name). If the plugin is missing, stop and "
        f"tell the user, then: uv run ca higgsfield fail {key} --error \"plugin missing\".",
        f"2. Model: {data['model']}. Character: the saved Higgsfield character "
        f"\"{data['characterName']}\"; the prompt opens with {data['characterToken']} (if the "
        "tool also takes a character or reference parameter, select that saved character "
        "there too; record the syntax that worked in docs/v5-implementation-notes.md).",
        f"3. Prompt: exactly the \"prompt\" field (no changes, no added text). Aspect ratio "
        f"{data['aspectRatio']}, {data['images']} image.",
        "4. The user's \"ok\" to the dry run covers this attempt (its credits are in the "
        "estimate); stop and ask only if the plugin reports more credits than "
        f"{data['estimate']['creditsPerImage']} x {data['maxAttempts']}.",
        f"5. Save the image as PNG to {data['expectedOutput']} (attempt "
        f"{len(data['attempts'])} of {data['maxAttempts']}).",
        f"6. Run: uv run ca higgsfield record {key} --file \"{data['expectedOutput']}\" "
        "--credits <credits the plugin reports>",
        f"7. If it fails: uv run ca higgsfield fail {key} --error \"<the reason>\" (no retry "
        "by yourself; a second attempt only comes from ca).",
        "8. Then continue the build: uv run ca content build \"<package folder>\"; the app "
        "checks Roman's position, crops, adds the German text, logo and CTA, and checks again.",
    ]


def record(root: Path, key: str, file: Path, credits: float | None) -> HiggsfieldJob:
    """`ca higgsfield record`: the delivered image of the current attempt."""
    path = root / key / JOB_FILE
    if not path.is_file():
        raise ImageRequestError(f"no Higgsfield job {key} (uv run ca higgsfield list)")
    job = HiggsfieldJob(path.parent, json.loads(path.read_text(encoding="utf-8")))
    if job.data["status"] == "failed":
        raise ImageRequestError(f"{key} failed after {len(job.data['attempts'])} attempts")
    current = job.attempt
    target = Path(str(current["expectedOutput"]))
    if not file.is_file():
        raise ImageRequestError(f"{file} is not a file")
    try:
        with Image.open(file) as opened:
            image = opened.convert("RGB")
    except OSError as error:
        raise ImageRequestError(f"{file} is not an image: {error}") from None
    want = job.data["aspectRatio"]
    width, height = _ratio(want)
    if abs(image.size[0] / image.size[1] - width / height) > 0.02:
        raise ImageRequestError(f"{file.name} is {image.size[0]}x{image.size[1]}, not "
                                f"{want} as requested")
    if file.resolve() != target.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
    # Credits the plugin did not report count as the estimate (marked), never as zero.
    estimate = float(job.data["estimate"]["creditsPerImage"])
    current.update(status="delivered", credits=credits if credits is not None else estimate,
                   creditsEstimated=credits is None,
                   recordedAt=datetime.now(UTC).isoformat(timespec="seconds"))
    job.data["status"] = "delivered"
    job.save()
    return job


def fail(root: Path, key: str, error: str) -> HiggsfieldJob:
    """`ca higgsfield fail`: the attempt failed at Higgsfield; one more if allowed."""
    path = root / key / JOB_FILE
    if not path.is_file():
        raise ImageRequestError(f"no Higgsfield job {key}")
    job = HiggsfieldJob(path.parent, json.loads(path.read_text(encoding="utf-8")))
    job.reject(f"Higgsfield: {error}")
    return job


def pending_jobs(root: Path) -> list[HiggsfieldJob]:
    found = []
    for path in sorted(root.glob(f"*/{JOB_FILE}")):
        job = HiggsfieldJob(path.parent, json.loads(path.read_text(encoding="utf-8")))
        if job.data["status"] == "pending":
            found.append(job)
    return found


class HiggsfieldSoulProvider:
    name = "higgsfield_soul"
    mode = "agent"

    def __init__(self, settings: Settings | None) -> None:
        self.settings = settings
        config = guidelines()["higgsfield"]
        credits = float(config["estimatedCreditsPerImage"])
        usd = round(credits * float(config["usdPerCredit"]), 4)
        self.capabilities = ProviderCapabilities(
            max_identity_refs=0, max_object_refs=0, max_style_refs=0, max_total_refs=0,
            aspect_ratios=frozenset(ALL_ASPECT_RATIOS), image_sizes=frozenset(IMAGE_SIZES),
            max_count=1, est_cost_usd_per_image={size: usd for size in IMAGE_SIZES},
            draws_text=False,
            identity_prompt=f"the saved Higgsfield character {config['characterName']}",
            cost_basis=(f"{credits:g} Higgsfield credits per image x "
                        f"${float(config['usdPerCredit']):g} per credit (estimate, not "
                        "calibrated); at most "
                        f"{config['maxAttempts']} attempts"))

    def root(self) -> Path:
        base = self.settings.output_dir.parent if self.settings is not None else Path("outputs")
        return base / "higgsfield"

    def waiting(self, request: ImageRequest) -> Path | None:
        """The job file while no checked image exists for this request (it is written)."""
        job = HiggsfieldJob.for_request(request, self.root())
        if job.data["status"] == "failed":
            return None  # generate() raises the failure with its reasons
        return None if job.delivered() is not None else job.path

    def generate(self, request: ImageRequest, model: str) -> ImageResult:
        job = HiggsfieldJob.for_request(request, self.root())
        if job.data["status"] == "failed":
            reasons = "; ".join(str(item.get("reason")) for item in job.data["attempts"])
            raise ImageProviderError(f"Roman's image failed after {len(job.data['attempts'])} "
                                     f"Higgsfield attempts ({reasons}); no fallback to another "
                                     "provider", cost_usd=_spent(job))
        delivered = job.delivered()
        if delivered is None:
            raise ImageAwaitingAgent(f"waiting for Codex: Higgsfield job {job.path}", job.path)
        with Image.open(delivered) as opened:
            image = opened.convert("RGB")
        checks = guidelines()["checks"]
        problems = zone_problems(image, str(job.data["side"]), float(checks["personZoneShare"]))
        if not problems and job.data["cropToTarget"]:
            try:
                image, box = safe_crop(image, _ratio(str(job.data["targetAspect"])),
                                       detect(image))
                job.attempt["crop"] = list(box)
            except CropError as error:
                problems.append(str(error))
        if problems:
            reason = "person zone: " + "; ".join(problems)
            if job.reject(reason):
                raise ImageAwaitingAgent(f"attempt rejected ({reason}); Higgsfield job "
                                         f"{job.path} asks for attempt "
                                         f"{len(job.data['attempts'])}", job.path)
            raise ImageProviderError(f"Roman's image failed twice ({reason}); no fallback",
                                     cost_usd=_spent(job))
        job.attempt["checks"] = {"personZone": "passed"}
        job.save()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        credits = job.credits()
        return ImageResult(
            images=[GeneratedImage(data=buffer.getvalue(), mime_type="image/png")],
            provider=self.name, model=str(job.data["model"]),
            provider_request_ids=[f"higgsfield-{job.data['key']}"],
            cost_usd=_spent(job),
            metrics={"credits": credits, "attempts": float(len(job.data["attempts"]))})


def _spent(job: HiggsfieldJob) -> float | None:
    """Every attempt's credits in USD (rejected attempts count too); None before any record."""
    credits = job.credits()
    usd = float(guidelines()["higgsfield"]["usdPerCredit"])
    return round(credits * usd, 4) if credits else None


def create_provider(settings: Settings | None = None) -> HiggsfieldSoulProvider:
    return HiggsfieldSoulProvider(settings)


__all__ = ["HiggsfieldJob", "HiggsfieldSoulProvider", "create_provider", "fail",
           "generation_aspect", "pending_jobs", "record", "zone_problems"]
