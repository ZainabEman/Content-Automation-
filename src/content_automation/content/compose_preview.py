"""`ca compose preview BG-x [--mode scene|cutout|photo-crop] [--placeholder]` (live fixes): the
raw checks, the composition and the overlay on the newest raw image already saved for the item,
with its brief copy or placeholder copy. No model or RunPod call. Writes
`<package>/previews/<BG-x>-<mode>.png` and `<BG-x>-raw-checks.json`.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

from PIL import Image

from content_automation.ai.image import comfyui_photo_prompt
from content_automation.content.review import package_part
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.core.jobs import DETAILS_FILE, Job
from content_automation.references import (
    BrandProfileError,
    ReferenceLibraryError,
    load_brand,
    load_company,
    select_logo_ref,
)
from content_automation.registry.db import RegistryError
from content_automation.registry.items import get_item
from content_automation.workflows.compose import (
    Copy,
    Mode,
    compose_config,
    compose_post,
    copy_problems,
    raw_checks,
)
from content_automation.workflows.image_job import raw_image
from content_automation.workflows.logo import LogoOverlay

PREVIEW_DIR = "previews"
PLACEHOLDER = (  # --placeholder: layout copy that meets the scene limits
    "KI-Agenten entlasten Ihren Kundenservice",
    "Viele Mittelständler verlieren Anfragen, weil niemand rechtzeitig antwortet. Ein "
    "KI-Agent beantwortet einfache Fragen sofort und gibt den Rest an Ihr Team.",
    ("Die zehn häufigsten Kundenfragen sammeln", "Antworten mit Ihrem Team freigeben",
     "Den KI-Agenten zuerst im Chat testen"))


def _logo(settings: Settings) -> LogoOverlay | None:
    try:
        brand = load_brand(settings.references_dir)
    except BrandProfileError:
        brand = None
    try:
        ref = select_logo_ref(settings.references_dir,
                              preferred=brand.logo_file if brand else None)
    except ReferenceLibraryError:
        return None
    return LogoOverlay(path=ref.path, source=ref.source, asset_id=ref.asset_id)


def preview(conn: sqlite3.Connection, settings: Settings, ref: str, mode: Mode | None,
            placeholder: bool = False) -> list[str]:
    item = get_item(conn, ref)
    found = package_part(settings, item)
    if found is None or not found[2].image_folders or not found[2].image_refs:
        raise RegistryError(f"{item.id}: no image saved for it yet (nothing to preview).")
    folder, part, entry = found
    job_dir = Path(entry.image_folders[-1])
    name = entry.image_refs[-1].partition("/")[2]
    raw = raw_image(job_dir, name) or job_dir / name
    if not raw.is_file():
        raise RegistryError(f"{item.id}: the raw image {raw.as_posix()} is missing.")
    job = Job.load(job_dir / DETAILS_FILE)
    try:
        brief: dict[str, Any] = json.loads((folder / "brief.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        brief = {}
    found_slot = brief.get(part)
    slot: dict[str, Any] = found_slot if isinstance(found_slot, dict) else {}
    company = load_company(settings.company_file)
    website = company.website if company is not None else ""
    found_points = slot.get("points")
    points: list[Any] = found_points if isinstance(found_points, list) else []
    copy = (Copy(PLACEHOLDER[0], PLACEHOLDER[1], website, PLACEHOLDER[2]) if placeholder else
            Copy(str(slot.get("headline") or ""),
                 str(slot.get("subheadline") or slot.get("audienceLine") or ""), website,
                 tuple(str(point) for point in points)))
    checks = raw_checks(raw, settings)
    copy_issues = copy_problems(copy, compose_config(settings), mode)
    with Image.open(raw) as source:
        made = compose_post(source.convert("RGB"), settings, job.params.aspect_ratio, copy,
                            _logo(settings), mode)
    out = folder / PREVIEW_DIR / f"{item.id}-{made.mode}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    made.image.save(out, format="PNG", optimize=True)
    report = out.with_name(f"{item.id}-raw-checks.json")
    atomic_write_text(report, json.dumps({
        "item": item.id, "raw": raw.as_posix(), "rawChecks": checks, "passed": not checks,
        "copy": copy_issues, "mode": made.mode, "notes": made.notes,
        "boxes": made.boxes, "photoPrompt": comfyui_photo_prompt(settings),
    }, indent=2, ensure_ascii=False) + "\n")
    return [
        f"{item.id}: preview {out.as_posix()} ({made.image.width}x{made.image.height}, mode "
        f"{made.mode}); no model call",
        "Raw checks: " + ("passed" if not checks else "FAIL: " + "; ".join(checks)),
        ("Copy (placeholder): " if placeholder else "Copy: ")
        + ("ok" if not copy_issues else "; ".join(copy_issues)),
        *[f"Note: {note}" for note in made.notes],
        f"Results: {report.as_posix()}",
    ]
