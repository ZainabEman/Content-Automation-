"""Production briefs (Phase 6 P6-D5): what the editor, the recording and the image pipeline
need, saved as `brief.json` + `brief.md` next to the script in v<n> (C6-2, C6-3).

- youtube: b-roll per section (stock, screen, own_footage, ai_generated), motion graphics,
  on-screen text, captions, thumbnail (text at most 5 words), chapters, music mood, presenter
  (Roman) and setting, assets needed, editor notes;
- social: the visual direction for the existing image pipeline.

The podcast brief was removed in v5 (PRD R8: no podcast media).
"""

import json
import sqlite3
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError

from content_automation.content.production import start_if_ready
from content_automation.content.script_check import Check, Saved
from content_automation.content.scripts import ScriptError, Template, build_template, words
from content_automation.core.config import Settings
from content_automation.core.files import CamelModel, atomic_write_text
from content_automation.registry.artifacts import add_artifact, latest_artifact, log_invalid

THUMBNAIL_WORDS = 5
SourceHint = Literal["stock", "screen", "own_footage", "ai_generated"]


class _Model(CamelModel):
    model_config = ConfigDict(extra="forbid")


class BRoll(_Model):
    section: str
    description: str = Field(min_length=1)
    source_hint: SourceHint


class Captions(_Model):
    style: str = Field(min_length=1)
    language: str = Field(min_length=2)


class Thumbnail(_Model):
    concept: str = Field(min_length=1)
    text: str = Field(min_length=1)


class Chapter(_Model):
    title: str = Field(min_length=1)
    section: str


class Presenter(_Model):
    name: str = "Roman"
    setting: str = Field(min_length=1)


class _Brief(_Model):
    item: str
    version: int = Field(ge=1)


class YoutubeBrief(_Brief):
    type: Literal["youtube"]
    b_roll: list[BRoll] = Field(min_length=1)
    motion_graphics: list[str] = Field(default_factory=list)
    on_screen_text: list[str] = Field(default_factory=list)
    captions: Captions
    thumbnail: Thumbnail
    chapters: list[Chapter] = Field(min_length=1)
    music_mood: str = Field(min_length=1)
    presenter: Presenter
    assets_needed: list[str] = Field(default_factory=list)
    editor_notes: str = ""


class SocialBrief(_Brief):
    type: Literal["social"]
    visual_direction: str = Field(min_length=1)


Brief = Annotated[YoutubeBrief | SocialBrief, Field(discriminator="type")]
_BRIEF: TypeAdapter[YoutubeBrief | SocialBrief] = TypeAdapter(Brief)


def brief_type(template: Template) -> str:
    return template.formula.brief or "social"


def skeleton(template: Template) -> dict[str, Any]:
    keys = [spec.key for spec in template.formula.sections]
    base: dict[str, Any] = {"item": template.item.id, "version": template.version,
                            "type": brief_type(template)}
    if base["type"] == "youtube":
        base |= {"bRoll": [{"section": keys[0], "description": "", "sourceHint": "stock"}],
                 "motionGraphics": [], "onScreenText": [],
                 "captions": {"style": "", "language": template.language},
                 "thumbnail": {"concept": "", "text": ""},
                 "chapters": [{"title": "", "section": key} for key in keys],
                 "musicMood": "", "presenter": {"name": "Roman", "setting": ""},
                 "assetsNeeded": [], "editorNotes": ""}
    else:
        base |= {"visualDirection": ""}
    return base


def template_json(template: Template) -> dict[str, Any]:
    return {"item": template.item.id, "version": template.version,
            "type": brief_type(template), "formula": template.formula_name,
            "language": template.language, "sections": [s.key for s in template.formula.sections],
            "minutes": list(template.formula.minutes) if template.formula.minutes else None,
            "rules": {"thumbnailWords": THUMBNAIL_WORDS,
                      "sourceHints": ["stock", "screen", "own_footage", "ai_generated"]},
            "storesIn": template.stores_in.as_posix(), "skeleton": skeleton(template)}


def read_brief(path: Path) -> YoutubeBrief | SocialBrief:
    try:
        return _BRIEF.validate_json(path.read_text(encoding="utf-8"))
    except OSError:
        raise ScriptError(f"Brief file not found: {path}.") from None
    except ValidationError as error:
        fields = sorted({".".join(str(p) for p in issue["loc"]) for issue in error.errors()})
        raise ScriptError(f"{path.name} is not a production brief; check: "
                          f"{', '.join(fields)}.") from None


def check_brief(conn: sqlite3.Connection, template: Template,
                brief: YoutubeBrief | SocialBrief) -> Check:
    check = Check()
    keys = {spec.key for spec in template.formula.sections}
    if brief.item.upper() != template.item.id:
        check.problems.append(f"item is {brief.item}, not {template.item.id}")
    if brief.version != template.version:
        check.problems.append(f"version is {brief.version}; the current version is "
                              f"v{template.version}")
    if brief.type != brief_type(template):
        check.problems.append(f"type is {brief.type}; {template.formula_name} needs "
                              f"{brief_type(template)}")
    if isinstance(brief, YoutubeBrief):
        used = [b.section for b in brief.b_roll] + [c.section for c in brief.chapters]
        check.problems += [f"{key}: not a section of {template.formula_name}"
                           for key in sorted(set(used) - keys)]
        if words(brief.thumbnail.text) > THUMBNAIL_WORDS:
            check.problems.append(f"thumbnail.text: {words(brief.thumbnail.text)} words "
                                  f"(at most {THUMBNAIL_WORDS})")
        if brief.captions.language != template.language:
            check.problems.append(f"captions.language is {brief.captions.language}; the "
                                  f"content language is {template.language}")
        if not brief.presenter.name.strip():
            check.problems.append("presenter.name: missing (Roman)")
    elif words(brief.visual_direction) < 5:
        check.problems.append("visualDirection: at least 5 words for the image pipeline")
    if latest_artifact(conn, template.item.id, template.formula.artifact,
                       template.version) is None:
        check.warnings.append(f"no saved {template.formula.artifact} for v{template.version} "
                              "yet")
    return check


def render_brief(template: Template, brief: YoutubeBrief | SocialBrief) -> str:
    out = [f"# Production brief: {template.item.title}", "",
           f"{template.item.id} v{brief.version} · {brief.type}", ""]
    if isinstance(brief, YoutubeBrief):
        out += [f"Presenter: {brief.presenter.name} — {brief.presenter.setting}",
                f"Music: {brief.music_mood}",
                f"Captions: {brief.captions.style} ({brief.captions.language})",
                f'Thumbnail: {brief.thumbnail.concept} — "{brief.thumbnail.text}"', "",
                "## Chapters", *[f"- {c.title} ({c.section})" for c in brief.chapters], "",
                "## B-roll", *[f"- {b.section}: {b.description} [{b.source_hint}]"
                               for b in brief.b_roll], ""]
        for title, values in (("Motion graphics", brief.motion_graphics),
                              ("On-screen text", brief.on_screen_text),
                              ("Assets needed", brief.assets_needed)):
            if values:
                out += [f"## {title}", *[f"- {value}" for value in values], ""]
        if brief.editor_notes:
            out += ["## Editor notes", brief.editor_notes, ""]
    else:
        out += ["## Visual direction", brief.visual_direction, ""]
    return "\n".join(out).rstrip() + "\n"


def save_brief(conn: sqlite3.Connection, settings: Settings, ref: str, draft: Path, *,
               command: str | None = None) -> Saved:
    template = build_template(conn, settings, ref)
    brief = read_brief(draft)
    check = check_brief(conn, template, brief)
    folder = template.stores_in
    if not check.ok:
        log_invalid(conn, template.item.id, template.version, "brief", check.problems,
                    command=command)
        return Saved(check, None, folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "brief.json"
    stored = brief.model_copy(update={"item": template.item.id})
    atomic_write_text(path, json.dumps(stored.model_dump(by_alias=True), indent=2,
                                       ensure_ascii=False) + "\n")
    atomic_write_text(folder / "brief.md", render_brief(template, stored))
    artifact = add_artifact(conn, template.item.id, template.version, "brief", path.as_posix(),
                            check.as_json(), command=command)
    started = start_if_ready(conn, template.item.id, command=command)
    if started:
        check.notes.append(started)
    return Saved(check, artifact, folder)


def stored_brief(conn: sqlite3.Connection, settings: Settings, ref: str,
                 version: int | None = None
                 ) -> tuple[Template, YoutubeBrief | SocialBrief, Path]:
    template = build_template(conn, settings, ref)
    found = latest_artifact(conn, ref, "brief", version)
    if found is None:
        raise ScriptError(f"{template.item.id} has no saved production brief"
                          + (f" for v{version}" if version else "")
                          + f": `uv run ca brief template {template.item.id}` first.")
    path = Path(found.path)
    return template, read_brief(path), path
