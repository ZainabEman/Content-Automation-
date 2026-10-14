"""Clips from a finished video (Phase 9 Step 1): Opus Pro as a manual provider.

config/clips.json `provider: manual` (default): `ca clips handoff BG-x` writes the note for the
person who runs Opus Pro (the video, 10-12 candidates, 9:16); `ca clips import BG-x <folder>`
turns the returned files into candidate `short` items (parent = the video; vertical, 15-90 s);
`ca clips select BG-x 2 5 7 9` approves the user's picks and rejects the rest ("not selected");
4-5 picks (config) unless --force. `provider: api` is a stub: "not configured".
"""

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from content_automation.content.production import base_dir, version_dir
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.core.media import MediaError, probe_media
from content_automation.registry.approvals import approve, reject
from content_automation.registry.artifacts import add_artifact, latest_artifact
from content_automation.registry.db import RegistryError
from content_automation.registry.ids import resolve
from content_automation.registry.items import Item, add_alias, children, create_item, get_item
from content_automation.registry.progress import part_done

VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm")
DEFAULTS: dict[str, Any] = {"provider": "manual", "candidates": [10, 12], "select": [4, 5],
                            "seconds": [15, 90], "aspect": "9:16"}


def clips_config(settings: Settings) -> dict[str, Any]:
    try:
        data = json.loads(settings.clips_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {**DEFAULTS, **(data if isinstance(data, dict) else {})}


def _provider(settings: Settings) -> None:
    provider = clips_config(settings)["provider"]
    if provider == "api":
        raise RegistryError("Clips provider api: not configured (Opus Pro API; use manual).")
    if provider != "manual":
        raise RegistryError(f'Unknown clips provider "{provider}" (manual or api).')


def _video(conn: sqlite3.Connection, ref: str) -> Item:
    item = get_item(conn, ref)
    if item.kind != "youtube":
        raise RegistryError(f"{item.id} is a {item.kind}: clips come from a YouTube video.")
    if item.production_status != "final" or item.review_status != "approved":
        raise RegistryError(f"{item.id}: clips need production final and review approved "
                            f"(production {item.production_status}, review {item.review_status}).")
    return item


def clips_handoff(conn: sqlite3.Connection, settings: Settings, ref: str, *,
                  command: str | None = None) -> list[str]:
    _provider(settings)
    video = _video(conn, ref)
    final = latest_artifact(conn, video.id, "final", video.approved_version)
    if final is None:
        raise RegistryError(f"{video.id} has no imported final for v{video.approved_version}.")
    config = clips_config(settings)
    low, high = config["candidates"]
    note = version_dir(settings, video) / "clips" / "handoff.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(note, (
        f"# Clips for {video.title} ({video.id})\n\nVideo: {final.path}\n\n"
        f"Please make {low}-{high} candidate clips in Opus Pro, {config['aspect']} (vertical), "
        f"{config['seconds'][0]}-{config['seconds'][1]} seconds each, and return them as MP4 "
        f"files in one folder.\nThen: `uv run ca clips import {video.id} <folder>`.\n"))
    add_artifact(conn, video.id, video.current_version, "handoff", note.as_posix(),
                 {"ok": True, "clips": [low, high]}, actor="user", command=command)
    return [f"{video.id}: clips handoff {note.as_posix()} ({low}-{high} candidates, "
            f"{config['aspect']})"]


def _clip_problems(path: Path, seconds: list[int]) -> list[str]:
    try:
        info = probe_media(path)
    except MediaError as error:
        return [f"does not decode ({error})"]
    problems = []
    if not (info.width and info.height and info.height > info.width):
        problems.append(f"{info.width}x{info.height} is not vertical")
    duration = info.duration_sec or 0.0
    if not seconds[0] <= duration <= seconds[1]:
        problems.append(f"{duration:.1f} s (allowed {seconds[0]}-{seconds[1]} s)")
    return problems


def clips_import(conn: sqlite3.Connection, settings: Settings, ref: str, folder: Path, *,
                 command: str | None = None) -> list[str]:
    _provider(settings)
    video = _video(conn, ref)
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES) \
        if folder.is_dir() else []
    if not files:
        raise RegistryError(f"No video files in {folder}.")
    seconds = list(clips_config(settings)["seconds"])
    number = len([c for c in children(conn, video.id) if c.kind == "short"])
    target = base_dir(settings, video) / "clips"
    lines = []
    for file in files:
        problems = _clip_problems(file, seconds)
        if problems:
            lines.append(f"{file.name}: not imported ({'; '.join(problems)})")
            continue
        number += 1
        clip = create_item(conn, kind="short", title=f"{video.title} — clip {number}",
                           topic=video.topic, platforms=["youtube", "tiktok", "instagram"],
                           parent_id=video.id, deliverable="youtube_short", command=command)
        add_alias(conn, clip.id, f"{video.id}#clip{number}", command=command)
        copy = target / f"clip_{number:02d}{file.suffix.lower()}"
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, copy)
        add_artifact(conn, clip.id, 1, "final", copy.as_posix(),
                     {"ok": True, "source": file.resolve().as_posix()}, actor="user",
                     command=command)
        lines.append(f"Candidate {number}: {clip.id} ({copy.as_posix()})")
    lines.append(f"Next: pick {'-'.join(str(n) for n in clips_config(settings)['select'])} "
                 f"clips: uv run ca clips select {video.id} <numbers>")
    return lines


def clips_select(conn: sqlite3.Connection, settings: Settings, ref: str, numbers: list[int],
                 *, force: bool = False, command: str | None = None) -> list[str]:
    video = get_item(conn, ref)
    low, high = clips_config(settings)["select"]
    if not force and not low <= len(set(numbers)) <= high:
        raise RegistryError(f"Pick {low}-{high} clips (got {len(set(numbers))}); --force for "
                            "another count.")
    candidates = {}
    for clip in children(conn, video.id):
        if clip.kind != "short" or clip.idea_status != "proposed":
            continue
        for number in range(1, 100):
            try:
                if resolve(conn, f"{video.id}#clip{number}") == clip.id:
                    candidates[number] = clip
                    break
            except RegistryError:
                continue
    unknown = [n for n in numbers if n not in candidates]
    if unknown:
        raise RegistryError(f"No open candidate {', '.join(map(str, unknown))} for {video.id} "
                            f"(open: {', '.join(map(str, sorted(candidates))) or 'none'}).")
    lines = []
    for number, clip in sorted(candidates.items()):
        if number in numbers:
            approve(conn, clip.id, gate="idea", command=command, note="selected clip")
            part_done(conn, clip.id, command=command)
            lines.append(f"Clip {number} {clip.id}: approved")
        else:
            reject(conn, clip.id, "not selected", gate="idea", command=command)
            lines.append(f"Clip {number} {clip.id}: rejected (not selected)")
    return lines
