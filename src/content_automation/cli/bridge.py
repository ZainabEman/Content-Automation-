"""Glue between the `ca` commands and the registry (§14 D-1..D-6): cost lines for direct runs,
package registration, agent-step jobs and rejected images. Thin; the rules live in registry/."""

import sqlite3
from pathlib import Path

from content_automation.ai.image import ImageRequest, estimate_cost_usd
from content_automation.content.deliverables import DeliverableCatalog
from content_automation.content.package import PACKAGE_FILE, load_package
from content_automation.core.agent_steps import load_request
from content_automation.core.config import Settings
from content_automation.registry import runtime
from content_automation.registry.db import RegistryError
from content_automation.registry.dryruns import CostLine
from content_automation.registry.jobs import find_by_result, load_job_config, reject_job
from content_automation.registry.link import package_item, register_package
from content_automation.workflows.video_job import PreparedVideo

LEGACY_REQUEST = "build requested for a package made before the registry"


def image_cost_line(request: ImageRequest, settings: Settings, *, label: str) -> CostLine:
    config = load_job_config(settings.jobs_file)
    provider = settings.image_provider
    estimate = estimate_cost_usd(request, settings)
    return CostLine(None, "image", provider, config.unit(provider), estimate, estimate, label)


def video_cost_lines(prepared: PreparedVideo, settings: Settings) -> list[CostLine]:
    """Per paid plugin scene of a direct `ca video`: the credit estimate from config/jobs.json."""
    config = load_job_config(settings.jobs_file)
    lines = []
    for item in prepared.scenes:
        if not config.paid(item.provider):
            continue
        job_type = "video_scene" if item.scene.type == "video" else "avatar_scene"
        estimate = config.estimate(job_type, item.provider) or 0.0
        lines.append(CostLine(None, job_type, item.provider, config.unit(item.provider),
                              estimate, estimate, f"scene {item.scene.n}"))
    return lines


def package_registration(
    conn: sqlite3.Connection, folder: Path, catalog: DeliverableCatalog, *,
    request: str | None, command: str | None, legacy: bool = False,
) -> list[str]:
    """Register the package's deliverables as items (D-1, D-3); the lines name the BG IDs.
    legacy: `ca content build` of a package from before the registry (only missing items)."""
    if not (folder / PACKAGE_FILE).is_file():
        return []
    package = load_package(folder)
    names = [key for key in package.deliverables if key in catalog.deliverables]
    if legacy and all(package_item(conn, folder, key) is not None for key in names):
        return []
    results = register_package(
        conn, folder, topic=package.topic, deliverables=names,
        kinds={key: catalog.deliverables[key].item_kind for key in names},
        platforms={key: catalog.deliverables[key].platform for key in names},
        content_id=package.content_id,
        source_refs=[package.research_source] if package.research_source else [],
        request=LEGACY_REQUEST if legacy else request, command=command,
    )
    return [
        f"{item.id} {item.deliverable}: {'registered' if created else 'already registered'} "
        f"(idea {item.idea_status}, v{item.current_version})"
        for item, created in results if created or not legacy
    ]


def record_agent_job(job_folder: Path, step: str, *, credits: float | None = None,
                     result: str | None = None, error: str | None = None) -> str | None:
    """Close the registry job of an agent step (its jobId in the request file)."""
    try:
        job_id = load_request(job_folder, step).job_id
    except (OSError, ValueError):
        return None
    if job_id is None:
        return None
    try:
        if error is not None:
            closed = runtime.fail(job_id, error, actual=credits)
        else:
            closed = runtime.succeed(job_id, actual=credits, result_path=result)
    except RegistryError as problem:
        return f"Registry: {problem}"
    return f"Registry: {closed.line()}" if closed is not None else None


def reject_image_job(conn: sqlite3.Connection, job_folder: Path, reason: str, *,
                     command: str | None) -> None:
    """A failed person or set check: that image job's result is never reused (D-6)."""
    found = find_by_result(conn, job_folder.as_posix())
    if found is not None and not found.rejected_at:
        reject_job(conn, found.id, reason, command=command)
