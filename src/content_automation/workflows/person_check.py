"""Track L person check, part 1: the automatic face check (free and local, OpenCV Haar
cascades from opencv-python-headless).

Roman alone: exactly one face; a group scene (a groupWords word of config/comfyui.json in the
prompt): at least one. No face may sit in the text-overlay zone (the job's textBoxes). Part 2 is
Codex's visual check, recorded with `ca job review <job> --person pass|fail "<reason>"`. A fail
of either part makes the image again once (content/package.py); a second fail stops.
"""

import json
import re
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from content_automation.core.config import Settings
from content_automation.core.jobs import Job
from content_automation.lora import face_boxes
from content_automation.workflows.compose import raw_checks
from content_automation.workflows.image_job import raw_image

DEFAULT_GROUP_WORDS = ("group", "team", "colleagues", "audience", "crowd")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
Box = tuple[float, float, float, float]  # left, top, right, bottom as shares of the image


def group_words(settings: Settings) -> tuple[str, ...]:
    path = Path(settings.comfyui_config_file)
    path = path if path.is_absolute() or path.exists() else _PROJECT_ROOT / path
    try:
        words = json.loads(path.read_text(encoding="utf-8")).get("groupWords")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_GROUP_WORDS
    return tuple(str(word) for word in words) if isinstance(words, list) else DEFAULT_GROUP_WORDS


def is_group(prompt: str, words: tuple[str, ...]) -> bool:
    pattern = r"\b(" + "|".join(re.escape(word) for word in words) + r")s?\b"
    return bool(words) and re.search(pattern, prompt, re.IGNORECASE) is not None


def face_problems(image: Path, *, group: bool, text_boxes: list[Box]) -> list[str]:
    """What the face check found wrong (empty: passed)."""
    try:
        with Image.open(image) as source:
            faces = face_boxes(ImageOps.exif_transpose(source).convert("RGB"))
    except (OSError, UnidentifiedImageError):
        return [f"{image.name} is not a readable image"]
    problems = []
    if group and not faces:
        problems.append("no face found (a group scene needs at least one)")
    elif not group and len(faces) != 1:
        problems.append(f"{len(faces)} faces found (Roman alone needs exactly 1)")
    for left, top, right, bottom in faces:
        x, y = (left + right) / 2, (top + bottom) / 2
        if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in text_boxes):
            problems.append("a face sits in the text-overlay zone")
            break
    return problems


def text_boxes(job: Job) -> list[Box]:
    try:
        boxes = json.loads(str(job.inputs.get("textBoxes") or "[]"))
    except ValueError:
        return []
    return [(float(b[0]), float(b[1]), float(b[2]), float(b[3])) for b in boxes if len(b) == 4]


def check_job_image(job: Job, name: str, settings: Settings) -> list[str]:
    """The face check of one output image (the model's image, before text and logo). A mock
    image is a placeholder without a face: not checked (the person check says so)."""
    if job.provider == "mock":
        return []
    image = raw_image(job.folder, name) or job.folder / name
    if job.provider == "comfyui":  # live fix: the raw studio photo: no text, one big face
        return raw_checks(image, settings)
    return face_problems(image, group=is_group(job.prompt, group_words(settings)),
                         text_boxes=text_boxes(job))
