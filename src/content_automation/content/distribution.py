"""Prepare and publish (Phase 9 Step 2).

- config/platforms.json: the sizes per platform variant (YouTube 16:9; Shorts, TikTok and Reels
  9:16; Instagram 1:1 and 4:5; LinkedIn and Facebook 1:1; Facebook ads 1:1, 4:5 and 9:16).
- `ca prepare BG-x [--platforms]`: the approved version's images and videos resized into
  `versions/v<n>/platforms/<variant>/` (images cropped with PIL, videos with FFmpeg).
- `ca copy template|save BG-x --platform p`: per-platform copy through the Phase 6 check
  (social_graphic formula with that platform's rules), saved next to the variant.
- A platform is ready when its variant and copy exist and the review is approved.
- `ca publish list|mark|fail`: no direct integrations (config/publishing.json `integrations:
  {}`); published needs the post's URL.
"""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from content_automation.content.production import version_dir
from content_automation.content.review import package_part
from content_automation.content.script_check import (
    Check,
    check_script,
    read_script,
    render_markdown,
)
from content_automation.content.scripts import Template, build_template, load_formulas
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.core.media import run_ffmpeg
from content_automation.registry.artifacts import add_artifact, latest_artifact
from content_automation.registry.db import RegistryError
from content_automation.registry.items import (
    Item,
    get_item,
    list_items,
    publication_summary,
    publications,
    set_publication_url,
    set_status,
)
from content_automation.registry.strategy import load_content

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm")
PUBLICATION_OF = {"shorts": "youtube", "reels": "instagram", "facebook_ads": "facebook"}


def platforms_config(settings: Settings) -> dict[str, list[str]]:
    try:
        data = json.loads(settings.platforms_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    sizes = data.get("sizes", {}) if isinstance(data, dict) else {}
    return {str(key): [str(size) for size in value] for key, value in sizes.items()}


def variant_of(item: Item, platform: str) -> str:
    """The variant key of one of the item's publication platforms."""
    if item.kind == "short":
        return {"youtube": "shorts", "instagram": "reels"}.get(platform, platform)
    if item.kind == "ad" and platform == "facebook":
        return "facebook_ads"
    return platform


def publication_of(variant: str) -> str:
    return PUBLICATION_OF.get(variant, variant)


def _sources(conn: sqlite3.Connection, settings: Settings, item: Item) -> list[Path]:
    version = item.approved_version or item.current_version
    final = latest_artifact(conn, item.id, "final", version)
    if final is not None:
        return [Path(final.path)]
    found = package_part(settings, item)
    if found is None:
        return []
    folder, _, entry = found
    return [folder / name for name in entry.files
            if (folder / name).suffix.lower() in (*IMAGE_SUFFIXES, *VIDEO_SUFFIXES)]


def platform_dir(settings: Settings, item: Item, variant: str) -> Path:
    return version_dir(settings, item) / "platforms" / variant


def _resize(source: Path, target: Path, size: str) -> None:
    width, height = (int(part) for part in size.split("x"))
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in IMAGE_SUFFIXES:
        with Image.open(source) as opened:
            ImageOps.fit(opened.convert("RGB"), (width, height)).save(target, optimize=True)
        return
    run_ffmpeg(["-y", "-i", str(source), "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}", "-c:a", "copy", str(target)], timeout_s=1800)


def prepare(conn: sqlite3.Connection, settings: Settings, ref: str,
            variants: list[str] | None, *, command: str | None = None
            ) -> tuple[list[str], list[tuple[Path, str]]]:
    """(lines, (file, variant) made); only the approved version."""
    item = get_item(conn, ref)
    if item.review_status != "approved":
        raise RegistryError(f"{item.id}: review is {item.review_status}; prepare follows the "
                            "review approval.")
    sizes = platforms_config(settings)
    chosen = variants or [variant_of(item, platform) for platform in item.platforms]
    unknown = [variant for variant in chosen if variant not in sizes]
    if unknown:
        raise RegistryError(f"Unknown platforms {', '.join(unknown)} (config/platforms.json: "
                            f"{', '.join(sizes)}).")
    sources = _sources(conn, settings, item)
    if not sources:
        raise RegistryError(f"{item.id} has no approved files to prepare.")
    lines: list[str] = []
    made: list[tuple[Path, str]] = []
    for variant in chosen:
        folder = platform_dir(settings, item, variant)
        for size in sizes[variant]:
            for source in sources:
                target = folder / f"{source.stem}_{size}{source.suffix.lower()}"
                _resize(source, target, size)
                made.append((target, variant))
        lines.append(f"{item.id} {variant}: {len(sources) * len(sizes[variant])} file(s) in "
                     f"{folder.as_posix()} ({', '.join(sizes[variant])})")
        lines += refresh_ready(conn, settings, item.id, variant, command=command)
    return lines, made


def copy_template(conn: sqlite3.Connection, settings: Settings, ref: str,
                  variant: str) -> Template:
    """The Phase 6 template with the social_graphic formula and this platform's rules."""
    template = build_template(conn, settings, ref) if _has_formula(conn, settings, ref) \
        else None
    formulas = load_formulas(settings.formulas_file)
    formula = formulas.formulas["social_graphic"]
    platform = publication_of(variant)
    item = get_item(conn, ref)
    base = template or Template(
        item=item, version=item.current_version, formula_name="social_graphic",
        formula=formula, language="en", platform=platform, rules=None, claims=[],
        feedback=None, total_words=None, stores_in=platform_dir(settings, item, variant))
    content = load_content(settings.content_file)
    touch = content.german_touch if content.for_platform(platform) == "en" else None
    return replace(base, formula_name="social_graphic", formula=formula, platform=platform,
                   rules=formula.platforms.get(platform), total_words=None,
                   stores_in=platform_dir(settings, item, variant), german_touch=touch)


def _has_formula(conn: sqlite3.Connection, settings: Settings, ref: str) -> bool:
    try:
        build_template(conn, settings, ref)
    except (RegistryError, ValueError):
        return False
    return True


def save_copy(conn: sqlite3.Connection, settings: Settings, ref: str, variant: str,
              draft: Path, *, command: str | None = None) -> tuple[Check, list[str]]:
    template = copy_template(conn, settings, ref, variant)
    script = read_script(draft)
    check = check_script(conn, template, script)
    if not check.ok:
        return check, []
    folder = template.stores_in
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "copy.json"
    atomic_write_text(path, json.dumps(script.model_dump(by_alias=True), indent=2,
                                       ensure_ascii=False) + "\n")
    atomic_write_text(folder / "copy.md", render_markdown(template, script, check))
    add_artifact(conn, template.item.id, template.version, "copy", path.as_posix(),
                 {**check.as_json(), "platform": variant}, command=command)
    return check, [f"{template.item.id} {variant}: copy saved ({path.as_posix()})",
                   *refresh_ready(conn, settings, template.item.id, variant, command=command)]


def refresh_ready(conn: sqlite3.Connection, settings: Settings, ref: str, variant: str, *,
                  command: str | None = None) -> list[str]:
    """not_ready -> ready once the variant and its copy exist and the review is approved."""
    item = get_item(conn, ref)
    platform = publication_of(variant)
    folder = platform_dir(settings, item, variant)
    has_variant = folder.is_dir() and any(
        p.suffix.lower() in (*IMAGE_SUFFIXES, *VIDEO_SUFFIXES) for p in folder.iterdir())
    if (publications(conn, item.id).get(platform) != "not_ready" or not has_variant
            or not (folder / "copy.json").is_file() or item.review_status != "approved"):
        return []
    set_status(conn, item.id, "publication", "ready", platform=platform, command=command)
    return [f"{item.id} {platform}: ready to publish"]


def publish_lines(conn: sqlite3.Connection, ready_only: bool) -> list[str]:
    lines = []
    for item in list_items(conn):
        for platform, status in publications(conn, item.id).items():
            if ready_only and status != "ready":
                continue
            if status == "not_ready" and not ready_only:
                continue
            lines.append(f"{item.id} {platform}: {status} — {item.title}")
    return lines or ["Nothing ready to publish." if ready_only else "Nothing prepared yet."]


def mark_published(conn: sqlite3.Connection, ref: str, platform: str, url: str, *,
                   command: str | None = None) -> list[str]:
    if not url.startswith(("http://", "https://")):
        raise RegistryError("Published needs the post's URL (http… or https…).")
    item = set_status(conn, ref, "publication", "published", platform=platform, actor="user",
                      command=command)
    set_publication_url(conn, item.id, platform, url, command=command)
    return [f"{item.id} {platform}: published {url}"]


def mark_failed(conn: sqlite3.Connection, ref: str, platform: str, reason: str, *,
                command: str | None = None) -> list[str]:
    if not reason.strip():
        raise RegistryError("A failed publication needs the reason.")
    item = set_status(conn, ref, "publication", "failed", platform=platform, actor="user",
                      command=command)
    set_publication_url(conn, item.id, platform, None, reason=reason, command=command)
    return [f"{item.id} {platform}: failed ({reason})"]


def publication_cell(conn: sqlite3.Connection, items: list[Item]) -> str:
    """Compact tracker cell: "linkedin published https://…; facebook ready"."""
    return "; ".join(text for item in items if (text := publication_summary(conn, item.id)))


def integrations(settings: Settings) -> dict[str, Any]:
    try:
        data = json.loads(settings.publishing_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    value = data.get("integrations", {}) if isinstance(data, dict) else {}
    return value if isinstance(value, dict) else {}
