"""`ca costs calibrate` (Phase 7 Step 2): the average actual amount per job of one provider
replaces its estimate in config — only with --apply.

Estimates in config: carousel stills/clips (config/carousel_design.json stills/clips
estimatedCredits, provider higgsfield-plugin) and video/avatar scenes (config/jobs.json
estimates.<job type>.<provider>). Other job types have no estimate in config to change.
"""

import json
import sqlite3
from pathlib import Path

from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.registry.jobs import cost_summary

CAROUSEL_KEYS = {"still": "stills", "clip": "clips"}


def calibrate(conn: sqlite3.Connection, settings: Settings, provider: str, *,
              apply: bool) -> list[str]:
    rows = [row for row in cost_summary(conn, provider) if row[6] > 0]
    if not rows:
        return [f"No succeeded {provider} jobs with an actual amount yet: nothing to calibrate."]
    design = json.loads(settings.carousel_design_file.read_text(encoding="utf-8"))
    jobs = json.loads(settings.jobs_file.read_text(encoding="utf-8"))
    lines: list[str] = []
    changed_design = changed_jobs = False
    for job_type, _, unit, count, estimate, actual, with_actual in rows:
        average = round(actual / with_actual, 2)
        if job_type in CAROUSEL_KEYS and provider == "higgsfield-plugin":
            section = design[CAROUSEL_KEYS[job_type]]
            lines.append(f"{job_type}: carousel_design.json {CAROUSEL_KEYS[job_type]}."
                         f"estimatedCredits {section.get('estimatedCredits')} -> {average:g} "
                         f"({with_actual} job(s))")
            section["estimatedCredits"] = average
            changed_design = True
        elif job_type in jobs.get("estimates", {}):
            values = jobs["estimates"][job_type]
            lines.append(f"{job_type}: jobs.json estimates.{job_type}.{provider} "
                         f"{values.get(provider)} -> {average:g} ({with_actual} job(s))")
            values[provider] = average
            changed_jobs = True
        else:
            lines.append(f"{job_type}: average {average:g} {unit} (estimate total {estimate:g} "
                         f"over {count} job(s)); no estimate in config to change")
    if not apply:
        return [*lines, "Nothing written: run again with --apply to write these values."]
    if changed_design:
        _write(settings.carousel_design_file, design)
    if changed_jobs:
        _write(settings.jobs_file, jobs)
    return [*lines, "Written to config." if changed_design or changed_jobs
            else "Nothing to write."]


def _write(path: Path, data: object) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
