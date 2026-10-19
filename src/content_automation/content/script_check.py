"""Checking, saving and rendering scripts and copy (Phase 6 P6-D3, D6).

The check is mechanical:
- every formula section is present and non-empty, no unknown sections, words within range
  (choices and "ends with" rules too), the total length within the formula's minutes;
- every claim_ref exists and belongs to the item or an ancestor up to its idea (C6-4);
- an outdated claim is an error; a disputed claim needs both sides named in the section notes
  (a source of each side); an unverified claim (opinions and speculation are never verified)
  is an error unless listed in acknowledged_unverified (then shown as a warning);
- a number, percent or year in a section needs a verified fact claim_ref in that section
  ("number without verified source", BR-07);
- platform rules: copy length, hook on its own first line, hashtag count.
A valid save writes `script.json` + `script.md` into v<current version> (C6-3); a refused one
writes nothing and is logged `artifact_invalid`.
"""

import json
import re
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from content_automation.content.copy_apply import apply_copy
from content_automation.content.german import check_texts
from content_automation.content.production import start_if_ready
from content_automation.content.scripts import (
    Script,
    ScriptError,
    Template,
    artifact_dir,
    build_template,
    lineage,
    load_formulas,
    words,
)
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.registry.artifacts import (
    Artifact,
    add_artifact,
    latest_artifact,
    log_invalid,
)
from content_automation.registry.claims import Claim, get_claim
from content_automation.registry.db import RegistryError
from content_automation.registry.items import get_item

_NUMBER = re.compile(r"\d")
# Sections only the team reads (briefing for the writer and the image pipeline)
INTERNAL_SECTIONS = frozenset({"central_message", "audience", "purpose", "visual_direction"})
_QUOTES = re.compile(r"[\"“”„«»]|(^|\s)['‘’]|['‘’](\s|$)")
_HIGHLIGHT = re.compile(r"\*([^*\s][^*]*)\*")
# First words that are not verbs (a bullet starts with what to do: "Review", "Ask", "Keep").
_NOT_VERBS = frozenset({
    "the", "a", "an", "your", "our", "their", "his", "her", "its", "this", "that", "these",
    "those", "my", "ai", "ki", "every", "all", "no", "each", "more", "less", "one", "two",
    "three", "why", "how", "what", "when", "who", "it", "we", "you", "they", "i", "if", "for",
    "with", "without", "in", "on", "at", "by", "to", "from", "and", "or", "but"})
_HASHTAG = re.compile(r"#\w+")


@dataclass
class Check:
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # what the save changed besides v<n>
    words: int = 0
    minutes: float | None = None

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_json(self) -> dict[str, Any]:
        return {"ok": self.ok, "problems": self.problems, "warnings": self.warnings,
                "notes": self.notes, "words": self.words, "minutes": self.minutes}


def read_script(path: Path) -> Script:
    try:
        return Script.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError:
        raise ScriptError(f"Script file not found: {path}.") from None
    except ValidationError as error:
        fields = sorted({".".join(str(p) for p in issue["loc"]) for issue in error.errors()})
        raise ScriptError(f"{path.name} is not a script.json; check: {', '.join(fields)}."
                          ) from None


def _claims(conn: sqlite3.Connection, template: Template, refs: list[str], where: str,
            check: Check) -> list[Claim]:
    allowed = {member.id for member in lineage(conn, template.item)}
    found: list[Claim] = []
    for ref in refs:
        try:
            claim = get_claim(conn, ref)
        except RegistryError:
            check.problems.append(f"{where}: claim {ref} does not exist")
            continue
        if claim.item_id not in allowed:
            check.problems.append(f"{where}: {claim.id} is research of {claim.item_id}, not of "
                                  f"{template.item.id} or its idea")
            continue
        found.append(claim)
    return found


def check_script(conn: sqlite3.Connection, template: Template, script: Script) -> Check:
    check = Check()
    formula = template.formula
    if script.item.upper() != template.item.id:
        check.problems.append(f"item is {script.item}, not {template.item.id}")
    if script.version != template.version:
        check.problems.append(f"version is {script.version}; the current version is "
                              f"v{template.version}")
    if script.formula != template.formula_name:
        check.problems.append(f"formula is {script.formula}, not {template.formula_name}")
    given = {section.key: section for section in script.sections}
    if len(given) != len(script.sections):
        check.problems.append("a section appears twice")
    for key in given.keys() - {spec.key for spec in formula.sections}:
        check.problems.append(f"{key}: not a section of {template.formula_name}")
    acknowledged = {ref.upper() for ref in script.acknowledged_unverified}
    for spec in formula.sections:
        section = given.get(spec.key)
        if section is None or not section.text.strip():
            if not spec.optional:
                check.problems.append(f"{spec.key}: missing or empty")
            continue
        text, count = section.text.strip(), words(section.text)
        low, high = spec.words
        if spec.key == "copy" and template.rules and template.rules.copy_words:
            low, high = template.rules.copy_words
        if not low <= count <= high:
            check.problems.append(f"{spec.key}: {count} words (allowed {low}-{high})")
        if spec.choices and text.lower() not in spec.choices:
            check.problems.append(f"{spec.key}: must be one of {', '.join(spec.choices)}")
        if spec.ends_with and not text.endswith(spec.ends_with):
            check.problems.append(f'{spec.key}: must end with "{spec.ends_with}"')
        lines = [line.strip().lstrip("-•* ").strip() for line in text.splitlines()
                 if line.strip()]
        if spec.lines and len(lines) != spec.lines:
            check.problems.append(f"{spec.key}: {len(lines)} lines (exactly {spec.lines})")
        if spec.line_words:
            check.problems += [f"{spec.key} line {number}: {words(line)} words (at most "
                               f"{spec.line_words})" for number, line in enumerate(lines, 1)
                               if words(line) > spec.line_words]
        found = [term for term in formula.banned_terms
                 if re.search(rf"\b{re.escape(term)}s?\b", text, re.IGNORECASE)]
        plain = text.replace("*", "")
        if spec.uppercase and plain != plain.upper():
            check.problems.append(f"{spec.key}: write it in capitals")
        if spec.prefixes and not any(plain.upper().startswith(prefix.upper())
                                     for prefix in spec.prefixes):
            check.problems.append(f"{spec.key}: start with one of {', '.join(spec.prefixes)}")
        if spec.highlights is not None and len(_HIGHLIGHT.findall(text)) != spec.highlights:
            check.problems.append(f"{spec.key}: mark exactly {spec.highlights} highlight "
                                  f"word like *word* (found {len(_HIGHLIGHT.findall(text))})")
        unknown = [line for line in lines if spec.line_choices and line not in spec.line_choices]
        if unknown:
            check.problems.append(f"{spec.key}: {', '.join(unknown)} not allowed (one of "
                                  f"{', '.join(spec.line_choices)})")
        if spec.verb_first:
            check.problems += [
                f"{spec.key} line {number}: start with a verb (\"{line.split()[0]}\" is not one)"
                for number, line in enumerate(lines, 1)
                if line.split()[0].lower().strip(".,:;!?") in _NOT_VERBS]
        if spec.no_quotes and _QUOTES.search(text):
            check.problems.append(f"{spec.key}: no quotes")
        layout = template.layout_language
        if spec.language == "de" and layout is not None and not layout.present(text):
            check.warnings.append(f"{spec.key}: reads as not German; {layout.rule()}")
        if found:
            check.problems.append(f"{spec.key}: jargon ({', '.join(found)}): say it in plain "
                                  "words")
        claims = _claims(conn, template, section.claim_refs, spec.key, check)
        for claim in claims:
            if claim.status == "outdated":
                check.problems.append(f"{spec.key}: {claim.id} is outdated ({claim.reason})")
            elif claim.status == "disputed":
                sides = (set(claim.source_refs), set(claim.counter_refs))
                named = set(re.findall(r"SRC-\d+", section.notes.upper()))
                if not all(side & named for side in sides):
                    check.problems.append(
                        f"{spec.key}: {claim.id} is disputed: name both sides in notes (one of "
                        f"{', '.join(sorted(sides[0]))} and one of {', '.join(sorted(sides[1]))})")
            elif claim.status == "unverified":
                if claim.id in acknowledged:
                    check.warnings.append(f"{spec.key}: uses {claim.id} ({claim.label}, "
                                          "unverified) — acknowledged")
                else:
                    check.problems.append(
                        f"{spec.key}: {claim.id} is {claim.label} and unverified: use another "
                        "claim or list it in acknowledgedUnverified (shown to the user)")
        if _NUMBER.search(text) and not any(c.label == "fact" and c.status == "verified"
                                            for c in claims):
            check.problems.append(f"{spec.key}: number without verified source")
        if spec.key == "copy" and template.rules:
            _platform(text, script, template, check)
    check.words = sum(words(section.text) for section in script.sections)
    if template.language == "de":  # v5 R1.6: the free German pass on what the audience sees
        german = check_texts((section.key, section.text) for section in script.sections
                             if section.key not in INTERNAL_SECTIONS)
        check.problems += german.errors
        check.warnings += german.warnings
    layout = template.layout_language
    caption = given.get("copy")
    if layout is not None and layout.caption_ends_german and caption is not None:
        ending = [line for line in caption.text.splitlines()
                  if line.strip() and not line.strip().startswith("#")]
        if ending and not layout.present(ending[-1]):
            check.warnings.append(f"copy: the caption should end with one German line; "
                                  f"{layout.rule()}")
    if template.total_words:
        low, high = template.total_words
        if not low <= check.words <= high:
            check.problems.append(f"length: {check.words} words (allowed {low}-{high}, "
                                  "the formula's minutes)")
    return check


def _platform(text: str, script: Script, template: Template, check: Check) -> None:
    rules = template.rules
    if rules is None:
        return
    lines = [line for line in text.splitlines() if line.strip()]
    if rules.hook_first_line and (len(lines) < 2 or words(lines[0]) > 25):
        check.problems.append(f"copy: {template.platform} needs the hook alone on the first line "
                              "(at most 25 words), then the body")
    if rules.hashtags:
        tags = set(script.hashtags) | set(_HASHTAG.findall(text))
        low, high = rules.hashtags
        if not low <= len(tags) <= high:
            check.problems.append(f"hashtags: {len(tags)} (allowed {low}-{high} on "
                                  f"{template.platform})")


def render_markdown(template: Template, script: Script, check: Check) -> str:
    item = template.item
    out = [f"# {item.title}", "",
           f"{item.id} v{script.version} · {script.formula} · {script.language} · "
           f"{check.words} words" + (f" · about {check.minutes:g} min" if check.minutes else ""),
           ""]
    if script.title_options:
        out += ["Title options:", *[f"- {title}" for title in script.title_options], ""]
    for section in script.sections:
        out += [f"## {section.key}", "", section.text.strip(), ""]
        if section.claim_refs:
            out += [f"Claims: {', '.join(section.claim_refs)}", ""]
        if section.notes:
            out += [f"Notes: {section.notes}", ""]
    if script.cta:
        out += [f"CTA: {script.cta}", ""]
    if script.hashtags:
        out += [" ".join(script.hashtags), ""]
    if check.warnings:
        out += ["Warnings:", *[f"- {warning}" for warning in check.warnings], ""]
    return "\n".join(out).rstrip() + "\n"


@dataclass(frozen=True)
class Saved:
    check: Check
    artifact: Artifact | None
    folder: Path


def save_script(conn: sqlite3.Connection, settings: Settings, ref: str, draft: Path, *,
                command: str | None = None) -> Saved:
    """Check the draft; valid: script.json + script.md in v<current> and an artifact row."""
    template = build_template(conn, settings, ref)
    script = read_script(draft)
    check = check_script(conn, template, script)
    folder = template.stores_in
    kind = template.formula.artifact
    if not check.ok:
        log_invalid(conn, template.item.id, template.version, kind, check.problems,
                    command=command)
        return Saved(check, None, folder)
    wpm = load_formulas(settings.formulas_file).words_per_minute.get(script.language, 150)
    check.minutes = round(check.words / wpm, 1) if template.formula.minutes else None
    stored = script.model_copy(update={"item": template.item.id, "word_count": check.words,
                                       "duration_minutes": check.minutes})
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "script.json"
    atomic_write_text(path, json.dumps(stored.model_dump(by_alias=True), indent=2,
                                       ensure_ascii=False) + "\n")
    if template.formula.artifact == "copy":  # P6-D8: the package's brief.json fields
        applied, warnings = apply_copy(template.item, stored)
        check.warnings += warnings
        if applied:
            check.notes.append(f"brief.json updated: {', '.join(applied)}")
    atomic_write_text(folder / "script.md", render_markdown(template, stored, check))
    artifact = add_artifact(conn, template.item.id, template.version, kind, path.as_posix(),
                            check.as_json(), command=command)
    started = start_if_ready(conn, template.item.id, command=command)
    if started:
        check.notes.append(started)
    return Saved(check, artifact, folder)


def stored_script(conn: sqlite3.Connection, settings: Settings, ref: str,
                  version: int | None = None) -> tuple[Template, Script, Path]:
    """The saved script of `version` (default: the newest saved one)."""
    template = build_template(conn, settings, ref)
    found = (latest_artifact(conn, ref, template.formula.artifact, version))
    if found is None:
        which = f"v{version}" if version else "any version"
        raise ScriptError(f"{template.item.id} has no saved {template.formula.artifact} for "
                          f"{which}: `uv run ca script template {template.item.id}` first.")
    path = Path(found.path)
    return template, read_script(path), path


def recheck(conn: sqlite3.Connection, settings: Settings, ref: str, version: int | None, *,
            command: str | None = None) -> tuple[Script, Check]:
    """Check a saved script again (claims may have changed); problems are logged."""
    template, script, _ = stored_script(conn, settings, ref, version)
    item = get_item(conn, ref)
    if script.version != template.version:  # an older version: checked as that version
        template = replace(template, version=script.version,
                           stores_in=artifact_dir(settings, item, script.version))
    check = check_script(conn, template, script)
    if not check.ok:
        log_invalid(conn, item.id, script.version, template.formula.artifact, check.problems,
                    command=command)
    return script, check
