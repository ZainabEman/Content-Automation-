"""The review gate and regeneration (Phase 7 Step 1).

- `ca review list`: items generated and not reviewed yet; `ca review show BG-x`: version, the
  part's files, checks, costs and the last feedback. Decisions stay `ca item approve|reject|
  revise` on the review gate.
- Regeneration after a review revise (v(n+1) pending): the reviewed files are kept in
  `<package>/versions/v<n>/` (never changed again); the parts named with --only (default all)
  are made again in the package, the others stay as they are (copied into v(n+1) unchanged).
  Image parts cost money (a dry run, then --authorize); the text is rendered into each image,
  so a text change regenerates that image. The new version starts at once, so review goes
  back to not_reviewed.
"""

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from content_automation.content.deliverables import load_deliverables
from content_automation.content.package import (
    PackageItem,
    image_checks,
    load_package,
    save_package,
)
from content_automation.core.config import Settings
from content_automation.registry.artifacts import list_artifacts
from content_automation.registry.db import RegistryError
from content_automation.registry.decisions import list_decisions
from content_automation.registry.dryruns import CostLine
from content_automation.registry.items import Item, get_item, list_items
from content_automation.registry.jobs import list_jobs
from content_automation.registry.versions import start_new_version

VERSIONS_DIR = "versions"
TEXT_PARTS = ("text", "caption", "overlay")


def review_queue(conn: sqlite3.Connection) -> list[Item]:
    return [item for item in list_items(conn)
            if item.generation_status == "generated" and item.review_status == "not_reviewed"]


def package_part(settings: Settings, item: Item) -> tuple[Path, str, PackageItem] | None:
    """The item's package folder, its part (post, carousel, ad, video) and that part."""
    if not item.package_path or not item.deliverable:
        return None
    spec = load_deliverables(settings.deliverables_file).deliverables.get(item.deliverable)
    folder = Path(item.package_path)
    try:
        package = load_package(folder)
    except (OSError, ValueError):
        return None
    part = spec.part if spec is not None else item.deliverable
    found = package.items.get(part)
    return (folder, part, found) if found is not None else None


def last_feedback(conn: sqlite3.Connection, item: Item) -> str | None:
    revises = [d for d in list_decisions(conn, item.id) if d.action == "revise"]
    return revises[-1].text if revises else None


def show_lines(conn: sqlite3.Connection, settings: Settings, ref: str) -> list[str]:
    item = get_item(conn, ref)
    lines = [f"{item.id} v{item.current_version}: {item.title} ({item.deliverable or item.kind})",
             f"Generation {item.generation_status}, review {item.review_status}"]
    found = package_part(settings, item)
    if found is None:
        lines.append("Files: none registered (no package part)")
    else:
        folder, part, entry = found
        lines.append(f"Files ({part}, {folder.as_posix()}):")
        lines += [f"  {(folder / name).as_posix()}" for name in entry.files] or ["  none"]
        lines += [f"  check {line}" for line in image_checks(entry, settings)]
    for artifact in list_artifacts(conn, item.id):
        state = "OK" if artifact.check.get("ok") else "problems"
        lines.append(f"  {artifact.type} v{artifact.version}: {state} ({artifact.path})")
    totals: dict[str, list[float]] = {}
    for job in list_jobs(conn, item_id=item.id):
        key = f"{job.provider} {job.unit}"
        estimate, actual = totals.setdefault(key, [0.0, 0.0])
        totals[key] = [estimate + (job.estimate or 0.0), actual + (job.actual or 0.0)]
    lines.append("Costs: " + ("; ".join(f"{key}: estimate {e:g}, actual {a:g}"
                                         for key, (e, a) in totals.items()) or "none recorded"))
    lines.append(f"Last feedback: {last_feedback(conn, item) or '—'}")
    return lines


@dataclass(frozen=True)
class Regeneration:
    item: Item
    folder: Path
    part: str
    positions: list[int]  # 0-based images or slides to make again
    lines: list[CostLine]

    @property
    def names(self) -> str:
        noun = "slide" if self.part == "carousel" else "image"
        return ",".join(f"{noun}{position + 1}" for position in self.positions)


def plan_regeneration(conn: sqlite3.Connection, settings: Settings, ref: str,
                      only: list[str]) -> Regeneration:
    item = get_item(conn, ref)
    if item.review_status != "changes_requested":
        raise RegistryError(f"{item.id}: review is {item.review_status}; regenerate follows a "
                            f'review revise: uv run ca item revise {item.id} "<feedback>"')
    found = package_part(settings, item)
    if found is None or not found[2].files:
        raise RegistryError(f"{item.id} has no package files to regenerate.")
    folder, part, entry = found
    count = len([name for name in entry.files if not name.endswith(".txt")])  # images only
    positions: set[int] = set()
    for token in only or [str(n) for n in range(1, count + 1)]:
        word = token.strip().lower()
        if word in TEXT_PARTS:
            raise RegistryError(f"{item.id}: the text is rendered into each {part} image; "
                                "regenerate that image (its number) instead of text.")
        digits = re.findall(r"\d+", word)
        number = int(digits[-1]) if digits else 0
        if not 1 <= number <= count:
            raise RegistryError(f'"{token}": {item.id} has {count} {part} file(s); use '
                                f"1-{count}")
        positions.add(number - 1)
    per_image = round((entry.est_cost_usd or 0.0) / count, 6)
    lines = [CostLine(item.id, "image", settings.image_provider, "usd", per_image, per_image,
                      f"{part} {position + 1} again") for position in sorted(positions)]
    return Regeneration(item, folder, part, sorted(positions), lines)


def apply_regeneration(conn: sqlite3.Connection, plan: Regeneration, *,
                       command: str | None = None) -> list[str]:
    """Keep v<n>'s files, start v(n+1), mark the parts to make again (after the "ok")."""
    package = load_package(plan.folder)
    entry = package.items[plan.part]
    reviewed = plan.item.current_version - 1
    archive = plan.folder / VERSIONS_DIR / f"v{reviewed}"
    if not archive.exists():
        for name in entry.files:
            source = plan.folder / name
            if source.is_file():
                target = archive / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        archive.mkdir(parents=True, exist_ok=True)
        (archive / "version.json").write_text(json.dumps(
            {"item": plan.item.id, "version": reviewed, "part": plan.part,
             "files": entry.files}, indent=2) + "\n", encoding="utf-8")
    start_new_version(conn, plan.item.id, command=command)
    if plan.positions:
        entry.redo = sorted(set(entry.redo) | set(plan.positions))
        entry.status = "failed"
        entry.error = f"regenerate v{plan.item.current_version}: {plan.names}"
        save_package(plan.folder, package)
    kept = len(entry.files) - len(plan.positions)
    return [f"{plan.item.id}: v{reviewed} kept in {archive.as_posix()}; v"
            f"{plan.item.current_version} started ({plan.names} again, {kept} unchanged); "
            "review is not_reviewed again."]
