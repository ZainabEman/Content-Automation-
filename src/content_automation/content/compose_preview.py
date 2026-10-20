"""`ca compose preview BG-x [--mode scene|cutout|photo-crop] [--placeholder]` (live fixes): the
raw checks, the composition and the overlay on the newest raw image already saved for the item,
with its brief copy or placeholder copy. No model call. Writes
`<package>/previews/<BG-x>-<mode>.png` and `<BG-x>-raw-checks.json`.
"""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

from PIL import Image

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
from content_automation.workflows.card import Copy, Template
from content_automation.workflows.compose import (
    Mode,
    compose_config,
    compose_post,
    copy_problems,
    raw_checks,
)
from content_automation.workflows.image_job import raw_image
from content_automation.workflows.logo import LogoOverlay

PREVIEW_DIR = "previews"
PLACEHOLDER = Copy(  # --placeholder: card copy that meets the rules
    "Your hiring AI can be *wrong*", "KI im Recruiting braucht menschliche Kontrolle",
    bullets=("Review every AI shortlist", "Ask why candidates were rejected",
             "Keep the final decision human"),
    tag="AI RISK · HR", icons=("checklist", "search", "user-check"),
    cta_en="Follow for weekly AI checks", cta_de="Jetzt folgen")


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
            placeholder: bool = False, template: Template | None = None) -> list[str]:
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
    found_card = slot.get("card")
    card: dict[str, Any] = found_card if isinstance(found_card, dict) else {}
    if placeholder:
        copy = replace(PLACEHOLDER, website=website)
        if template == "stat":
            copy = replace(copy, stat="00%", stat_label="PREVIEW ONLY")
    else:
        copy = Copy(str(slot.get("headline") or ""),
                    str(card.get("subtitle") or slot.get("subheadline") or ""), website,
                    tuple(str(point) for point in points), tag=str(card.get("tag") or ""),
                    icons=tuple(card.get("icons") or ()), cta_en=str(card.get("ctaEn") or ""),
                    cta_de=str(card.get("ctaDe") or ""), stat=str(card.get("stat") or ""),
                    stat_label=str(card.get("statLabel") or ""),
                    highlight=tuple(str(word) for word in slot.get("highlight") or ()))
    checks = raw_checks(raw, settings)
    copy_issues = copy_problems(copy, compose_config(settings), mode)
    with Image.open(raw) as source:
        made = compose_post(source.convert("RGB"), settings, job.params.aspect_ratio, copy,
                            _logo(settings), mode, template=template, strict=False,
                            platform=item.platforms[0] if item.platforms else None)
    name = f"{template or made.mode}"
    out = folder / PREVIEW_DIR / f"{item.id}-{name}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    made.image.save(out, format="PNG", optimize=True)
    report = out.with_name(f"{item.id}-{name}-raw-checks.json")
    atomic_write_text(report, json.dumps({
        "item": item.id, "raw": raw.as_posix(), "rawChecks": checks, "passed": not checks,
        "copy": copy_issues, "mode": made.mode, "notes": made.notes,
        "boxes": made.boxes,
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
