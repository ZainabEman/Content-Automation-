"""Roman's images: Codex makes them with the Higgsfield plugin, model Soul 2.0 (agent adapter).

`ca` and Claude Code cannot call Codex plugins, so nothing is called here. A request becomes a
job file, outputs/_system/higgsfield/<key>/job.json (the prompt that opens with the saved
character's token, the character name, model Soul 2.0, the aspect ratio to generate (validated
against the Soul 2.0 list in config/roman_image_guidelines.json), one image, the expected output
path, the credit estimate and numbered instructions), and the job waits (ImageAwaitingAgent):
nothing is charged before an image exists. Codex makes the image, saves it to the expected path
and runs `ca higgsfield record <key> --file … --credits …` (or `ca higgsfield fail`), then the
package build again. Then this adapter returns the image: the placement check first (Roman fully
inside the outer personZoneShare, 40%, of the width on the planned side, nothing person-like in
the text side); when he is slightly too central, a person-safe shift crop (core/person_zone.py
shift_crop) moves him outward before anything else; then the person-safe crop to the canvas
aspect (3:4 to 4:5 for Facebook).

Never an automatic new image (2026-10-21): a failed check (or a failed plugin run) stops the row
(status needs_operator) and the operator chooses: `ca higgsfield accept <key> --file
<attempt.png>` (manual approval, logged in job.json; the build then continues from that image)
or `ca higgsfield retry <key>` (a new attempt, made only after a new dry run and the user's
"ok"). No fallback to another provider. Every attempt's credits are charged once: a registry job
reports only the credits not charged before (chargedCredits). """

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
from content_automation.core.person_zone import CropError, detect, safe_crop, shift_crop

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
    # the text side: everything outside his outer share
    empty = (0, int(width * (1 - share))) if side == "S-R" else (int(width * share), width)
    strays = [box for box in zone.regions
              if empty[0] <= (box[0] + box[2]) / 2 <= empty[1]]
    if strays:
        problems.append(f"{len(strays)} person-like region(s) in the text side")
    return problems


def placed(image: Image.Image, side: str, share: float
           ) -> tuple[Image.Image, list[str], tuple[int, int, int, int] | None]:
    """(the image, its placement problems, the shift crop used): when Roman is slightly too
    central, a person-safe shift crop is tried before a failure is reported."""
    problems = zone_problems(image, side, share)
    if not any(problem.startswith("Roman reaches") for problem in problems):
        return image, problems, None
    try:
        shifted, box = shift_crop(image, detect(image), side, share)
    except CropError:
        return image, problems, None
    if zone_problems(shifted, side, share):
        return image, problems, None
    return shifted, [], box


class HiggsfieldJob:
    """One Roman image request on disk (outputs/_system/higgsfield/<key>/job.json)."""

    def __init__(self, folder: Path, data: dict[str, Any]) -> None:
        self.folder = folder
        self.data = data

    @staticmethod
    def key_for_request(request: ImageRequest) -> str:
        key = (f"{request.prompt}|{request.aspect_ratio}|"
               f"{request.options.get('combination', '')}")
        return hashlib.sha256(key.encode()).hexdigest()[:12]

    @classmethod
    def for_request(cls, request: ImageRequest, root: Path) -> HiggsfieldJob:
        config = guidelines()
        higgsfield = config["higgsfield"]
        aspect = generation_aspect(request.aspect_ratio, config)
        if aspect not in higgsfield["aspectRatios"]:
            raise ImageRequestError(f"{aspect} is not a Soul 2.0 aspect ratio")
        key = cls.key_for_request(request)
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

    def stop(self, reason: str) -> None:
        """The current attempt failed (its check or the plugin): the row waits for the
        operator (accept or retry); never a new attempt by itself."""
        self.attempt.update(status="check_failed", reason=reason)
        self.data["status"] = "needs_operator"
        self.log(f"stopped: {reason}")
        self.save()

    def log(self, text: str) -> None:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        self.data.setdefault("log", []).append(f"{stamp} {text}")

    def uncharged_usd(self) -> float:
        """The credits not charged to a registry job yet, in USD (then marked charged)."""
        credits = self.credits() - float(self.data.get("chargedCredits") or 0)
        self.data["chargedCredits"] = self.credits()
        self.save()
        usd = float(guidelines()["higgsfield"]["usdPerCredit"])
        return round(max(0.0, credits) * usd, 4)

    def operator_message(self) -> str:
        key = self.data["key"]
        last = self.attempt
        return (f"Roman's Higgsfield image {key} stopped ({last.get('reason', 'see job.json')}); "
                "no new image is made by itself. The operator chooses: uv run ca higgsfield "
                f"accept {key} --file \"{last['expectedOutput']}\" (manual approval, logged; "
                f"the build then continues), or uv run ca higgsfield retry {key} (a new costed "
                "attempt, after a new dry run and the user's \"ok\")")

    def delivered(self) -> Path | None:
        accepted = self.data.get("accepted")
        if isinstance(accepted, dict):  # the operator's choice wins
            chosen = Path(str(accepted.get("file", "")))
            return chosen if chosen.is_file() else None
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
        "by yourself; a new attempt only when the operator runs ca higgsfield retry).",
        "8. Then continue the build: uv run ca content build \"<package folder>\"; the app "
        "checks Roman's position, crops, adds the German text and CTA (no logo, no website on "
        "a Roman creative), and checks again.",
    ]


def record(root: Path, key: str, file: Path, credits: float | None) -> HiggsfieldJob:
    """`ca higgsfield record`: the delivered image of the current attempt."""
    path = root / key / JOB_FILE
    if not path.is_file():
        raise ImageRequestError(f"no Higgsfield job {key} (uv run ca higgsfield list)")
    job = HiggsfieldJob(path.parent, json.loads(path.read_text(encoding="utf-8")))
    if job.data["status"] in ("failed", "needs_operator"):
        raise ImageRequestError(f"{key} waits for the operator: uv run ca higgsfield accept "
                                f"{key} --file <attempt.png>, or uv run ca higgsfield retry {key}")
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


def _load(root: Path, key: str) -> HiggsfieldJob:
    path = root / key / JOB_FILE
    if not path.is_file():
        raise ImageRequestError(f"no Higgsfield job {key} (uv run ca higgsfield list)")
    return HiggsfieldJob(path.parent, json.loads(path.read_text(encoding="utf-8")))


def fail(root: Path, key: str, error: str) -> HiggsfieldJob:
    """`ca higgsfield fail`: the attempt failed at Higgsfield; the operator decides next."""
    job = _load(root, key)
    job.stop(f"Higgsfield: {error}")
    return job


def accept(root: Path, key: str, file: Path, *,
           accept_text_zone_calm: bool = False) -> HiggsfieldJob:
    """`ca higgsfield accept`: the operator approves one attempt's image by hand (logged); the
    build continues from it without the placement check blocking (the shift crop is still used
    when it helps). The explicit text-zone option accepts only that failed check. Credits a
    failed build charged already are not charged again."""
    job = _load(root, key)
    if not file.is_file():
        raise ImageRequestError(f"{file} is not a file")
    try:
        with Image.open(file) as opened:
            size = opened.size
    except OSError as error:
        raise ImageRequestError(f"{file} is not an image: {error}") from None
    width, height = _ratio(str(job.data["aspectRatio"]))
    if abs(size[0] / size[1] - width / height) > 0.02:
        raise ImageRequestError(f"{file.name} is {size[0]}x{size[1]}, not "
                                f"{job.data['aspectRatio']} as requested")
    target = file.resolve()
    attempt = next((item for item in job.data["attempts"]
                    if Path(str(item.get("expectedOutput", ""))).resolve() == target), None)
    if attempt is None:  # a file from elsewhere: kept beside the job
        target = (job.folder / "accepted.png").resolve()
        shutil.copyfile(file, target)
    if job.data["status"] == "failed" and "chargedCredits" not in job.data:
        job.data["chargedCredits"] = job.credits()  # its failed build charged them already
    number = attempt["n"] if attempt is not None else None
    previous = job.data.get("accepted")
    checks = dict(previous.get("checks", {})) if isinstance(previous, dict) else {}
    if accept_text_zone_calm:
        checks["textZoneCalm"] = "accepted by the user for this image"
    job.data["accepted"] = {"attempt": number, "file": str(target), "by": "operator",
                            "at": datetime.now(UTC).isoformat(timespec="seconds"),
                            "checks": checks}
    if attempt is not None:
        attempt["accepted"] = True
    job.data["status"] = "delivered"
    accepted = ", accepted checks: textZoneCalm" if accept_text_zone_calm else ""
    job.log(f"accepted by the operator: {target.name} (attempt {number or 'external'})"
            f"{accepted}")
    job.save()
    return job


def retry(root: Path, key: str) -> HiggsfieldJob:
    """`ca higgsfield retry`: the operator orders one new, costed attempt (made by Codex after a
    new dry run and the user's "ok")."""
    job = _load(root, key)
    if job.data["status"] not in ("needs_operator", "failed"):
        raise ImageRequestError(f"{key} is {job.data['status']}: nothing to retry")
    job.data.pop("accepted", None)
    job.data["maxAttempts"] = max(int(job.data["maxAttempts"]), len(job.data["attempts"]) + 1)
    job.log(f"new attempt {len(job.data['attempts']) + 1} ordered by the operator")
    job.new_attempt()
    return job


def pending_jobs(root: Path, status: str = "pending") -> list[HiggsfieldJob]:
    found = []
    for path in sorted(root.glob(f"*/{JOB_FILE}")):
        job = HiggsfieldJob(path.parent, json.loads(path.read_text(encoding="utf-8")))
        if job.data["status"] == status:
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

    def has_charged_delivery(self, request: ImageRequest) -> bool:
        """True only when this exact request already has a delivered, fully charged image."""
        path = self.root() / HiggsfieldJob.key_for_request(request) / JOB_FILE
        if not path.is_file():
            return False
        job = HiggsfieldJob(path.parent, json.loads(path.read_text(encoding="utf-8")))
        charged = float(job.data.get("chargedCredits") or 0)
        return job.delivered() is not None and job.credits() <= charged

    def waiting(self, request: ImageRequest) -> Path | None:
        """The job file while no checked image exists for this request (it is written)."""
        job = HiggsfieldJob.for_request(request, self.root())
        if job.data["status"] in ("failed", "needs_operator"):
            return None  # generate() raises the failure with the operator's choices
        return None if job.delivered() is not None else job.path

    def generate(self, request: ImageRequest, model: str) -> ImageResult:
        job = HiggsfieldJob.for_request(request, self.root())
        if job.data["status"] in ("failed", "needs_operator"):
            raise ImageProviderError(job.operator_message() + "; no fallback to another "
                                     "provider", cost_usd=job.uncharged_usd())
        delivered = job.delivered()
        if delivered is None:
            raise ImageAwaitingAgent(f"waiting for Codex: Higgsfield job {job.path}", job.path)
        with Image.open(delivered) as opened:
            image = opened.convert("RGB")
        checks = guidelines()["checks"]
        accepted = job.data.get("accepted")
        record_to: dict[str, Any] = accepted if isinstance(accepted, dict) else job.attempt
        image, problems, shift = placed(image, str(job.data["side"]),
                                        float(checks["personZoneShare"]))
        if shift is not None:
            record_to["shift"] = list(shift)
        if problems and isinstance(accepted, dict):  # approved by the operator as it is
            record_to["acceptedDespite"] = "; ".join(problems)
            problems = []
        if not problems and job.data["cropToTarget"]:
            try:
                image, box = safe_crop(image, _ratio(str(job.data["targetAspect"])),
                                       detect(image))
                record_to["crop"] = list(box)
            except CropError as error:
                problems.append(str(error))
        if problems:
            job.stop("placement: " + "; ".join(problems))
            raise ImageProviderError(job.operator_message(), cost_usd=job.uncharged_usd())
        check_results = record_to.get("checks")
        if not isinstance(check_results, dict):
            check_results = {}
        check_results["personZone"] = ("accepted by the operator"
                                        if isinstance(accepted, dict) else "passed")
        record_to["checks"] = check_results
        job.save()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        credits = job.credits()
        return ImageResult(
            images=[GeneratedImage(data=buffer.getvalue(), mime_type="image/png")],
            provider=self.name, model=str(job.data["model"]),
            provider_request_ids=[f"higgsfield-{job.data['key']}"],
            cost_usd=job.uncharged_usd(),
            metrics={"credits": credits, "attempts": float(len(job.data["attempts"]))},
            manual_acceptances={
                name: str(reason)
                for name, reason in ((accepted.get("checks") or {}).items()
                                     if isinstance(accepted, dict) else [])
                if name == "textZoneCalm"
            })


def create_provider(settings: Settings | None = None) -> HiggsfieldSoulProvider:
    return HiggsfieldSoulProvider(settings)


__all__ = ["HiggsfieldJob", "HiggsfieldSoulProvider", "accept", "create_provider", "fail",
           "generation_aspect", "pending_jobs", "placed", "record", "retry", "zone_problems"]
