"""Editorial formulas and scripts (Phase 6 P6-D1, D2, D4, D7).

Codex writes the text; `ca` gives it a template and checks the result. The template names the
item's formula (config/formulas.json: by deliverable, then by kind), its sections with word
ranges, the platform rules, the content language (config/content.json), the claims of the item
and its ancestors up to the idea (C6-4) with the status `ca` decided, and the feedback of the
revise that made the current version. Files live in `<package>/scripts/<BG-x>/v<n>/` or, for
an item without a package, `<OUTPUT_DIR>/items/<BG-x>/scripts/v<n>/` (C6-1).
"""

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.core.config import Settings
from content_automation.core.files import CamelModel
from content_automation.registry.claims import Claim, list_claims
from content_automation.registry.decisions import list_decisions
from content_automation.registry.items import Item, get_item
from content_automation.registry.strategy import LayoutLanguage, load_content

SCRIPTS_DIR = "scripts"


class ScriptError(ValueError):
    """An invalid formulas file, an item without a formula, or an unreadable script."""


class _Model(CamelModel):
    model_config = ConfigDict(extra="forbid")


class SectionSpec(_Model):
    key: str = Field(min_length=1)
    what: str = ""
    words: tuple[int, int]
    choices: list[str] = Field(default_factory=list)
    ends_with: str | None = None
    optional: bool = False  # may be left out (the image fields of a post without him)
    lines: int | None = None  # exactly this many non-empty lines (e.g. 3 bullets)
    line_words: int | None = None  # at most this many words per line
    line_choices: list[str] = Field(default_factory=list)  # each line one of these (icons)
    uppercase: bool = False  # written in capitals (the tag)
    prefixes: list[str] = Field(default_factory=list)  # starts with one of these (pillar tags)
    highlights: int | None = None  # exactly this many *highlight* marks (the headline)
    verb_first: bool = False  # every line starts with a verb (bullets)
    no_quotes: bool = False  # no quotation marks
    language: str | None = None  # "de": the check warns when it reads as not German


class PlatformRules(_Model):
    copy_words: tuple[int, int] | None = None
    hook_first_line: bool = False
    hashtags: tuple[int, int] | None = None


class Formula(_Model):
    artifact: Literal["script", "copy"]
    brief: Literal["youtube"] | None = None
    minutes: tuple[int, int] | None = None
    sections: list[SectionSpec] = Field(min_length=1)
    platforms: dict[str, PlatformRules] = Field(default_factory=dict)
    banned_terms: list[str] = Field(default_factory=list)  # jargon the check refuses

    def section(self, key: str) -> SectionSpec | None:
        return next((spec for spec in self.sections if spec.key == key), None)


class Formulas(_Model):
    note: str | None = Field(default=None, alias="_note")
    words_per_minute: dict[str, int] = Field(default_factory=lambda: {"en": 150})
    by_deliverable: dict[str, str] = Field(default_factory=dict)
    by_kind: dict[str, str] = Field(default_factory=dict)
    formulas: dict[str, Formula] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        unknown = sorted({name for name in [*self.by_deliverable.values(),
                                            *self.by_kind.values()]} - set(self.formulas))
        if unknown:
            raise ValueError(f"unknown formulas: {', '.join(unknown)}")
        return self


class ScriptSection(_Model):
    key: str = Field(min_length=1)
    text: str = ""
    claim_refs: list[str] = Field(default_factory=list)
    notes: str = ""


class Script(_Model):
    """script.json (P6-D4); word_count and duration_minutes are computed by `ca`."""

    item: str
    version: int = Field(ge=1)
    formula: str
    language: str
    sections: list[ScriptSection]
    title_options: list[str] = Field(default_factory=list)
    cta: str = ""
    hashtags: list[str] = Field(default_factory=list)
    acknowledged_unverified: list[str] = Field(default_factory=list)
    word_count: int | None = None
    duration_minutes: float | None = None


def load_formulas(path: Path) -> Formulas:
    try:
        return Formulas.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError:
        raise ScriptError(f"Formulas file not found at {path}.") from None
    except ValidationError as error:
        fields = sorted({".".join(str(p) for p in issue["loc"]) or issue["msg"]
                         for issue in error.errors()})
        raise ScriptError(f"{path.name} is invalid; check: {', '.join(fields)}.") from None


def formula_for(item: Item, formulas: Formulas) -> tuple[str, Formula]:
    name = (formulas.by_deliverable.get(item.deliverable or "")
            or formulas.by_kind.get(item.kind))
    if name is None:
        raise ScriptError(
            f"{item.id} ({item.deliverable or item.kind}) has no formula in config/formulas.json "
            "(shorts and clips get scripts in Phase 9; ideas are planned first)."
        )
    return name, formulas.formulas[name]


def lineage(conn: sqlite3.Connection, item: Item) -> list[Item]:
    """The item, its parent, … up to the idea (C6-4)."""
    chain = [item]
    while chain[-1].parent_id and len(chain) < 10:
        chain.append(get_item(conn, chain[-1].parent_id))
    return chain


def research_claims(conn: sqlite3.Connection, item: Item) -> list[Claim]:
    return [claim for member in lineage(conn, item) for claim in list_claims(conn, member.id)]


def current_feedback(conn: sqlite3.Connection, item: Item) -> str | None:
    """The feedback of the revise that made the current version (P6-D7)."""
    revises = [d for d in list_decisions(conn, item.id)
               if d.action == "revise" and d.version < item.current_version]
    return revises[-1].text if revises else None


def artifact_dir(settings: Settings, item: Item, version: int) -> Path:
    if item.package_path:
        return Path(item.package_path) / SCRIPTS_DIR / item.id / f"v{version}"
    return settings.output_dir / "items" / item.id / SCRIPTS_DIR / f"v{version}"


def words(text: str) -> int:
    """Words with a letter or digit (a "·" separator or a "-" dash is not a word)."""
    return sum(any(char.isalnum() for char in token) for token in text.split())


@dataclass(frozen=True)
class Template:
    item: Item
    version: int
    formula_name: str
    formula: Formula
    language: str
    platform: str | None
    rules: PlatformRules | None
    claims: list[Claim]
    feedback: str | None
    total_words: tuple[int, int] | None
    stores_in: Path
    layout_language: LayoutLanguage | None = None  # config/content.json layoutLanguage

    def skeleton(self) -> Script:
        return Script(item=self.item.id, version=self.version, formula=self.formula_name,
                      language=self.language,
                      sections=[ScriptSection(key=spec.key) for spec in self.formula.sections])


def build_template(conn: sqlite3.Connection, settings: Settings, ref: str) -> Template:
    item = get_item(conn, ref)
    formulas = load_formulas(settings.formulas_file)
    name, formula = formula_for(item, formulas)
    platform = item.platforms[0] if item.platforms else None
    content = load_content(settings.content_file)
    language = content.for_platform(platform or "")
    wpm = formulas.words_per_minute.get(language, 150)
    total = ((formula.minutes[0] * wpm, formula.minutes[1] * wpm) if formula.minutes else None)
    return Template(
        item=item, version=item.current_version, formula_name=name, formula=formula,
        language=language, platform=platform, rules=formula.platforms.get(platform or ""),
        claims=research_claims(conn, item), feedback=current_feedback(conn, item),
        total_words=total,
        stores_in=artifact_dir(settings, item, item.current_version),
        layout_language=content.layout_language if language == "en" else None,
    )


def template_json(template: Template) -> dict[str, Any]:
    return {
        "item": template.item.id, "title": template.item.title,
        "version": template.version, "formula": template.formula_name,
        "artifact": template.formula.artifact, "language": template.language,
        "bannedTerms": template.formula.banned_terms,
        "layoutLanguage": ({**asdict(template.layout_language),
                            "rule": template.layout_language.rule()}
                           if template.layout_language else None),
        "platform": template.platform,
        "sections": [spec.model_dump(by_alias=True, exclude_defaults=True)
                     for spec in template.formula.sections],
        "totalWords": list(template.total_words) if template.total_words else None,
        "platformRules": (template.rules.model_dump(by_alias=True, exclude_none=True)
                          if template.rules else None),
        "claims": [{"id": c.id, "on": c.item_id, "label": c.label, "status": c.status,
                    "text": c.text, "sources": list(c.source_refs),
                    "counter": list(c.counter_refs)} for c in template.claims],
        "feedback": template.feedback,
        "storesIn": template.stores_in.as_posix(),
        "skeleton": template.skeleton().model_dump(by_alias=True, exclude_none=True),
    }


def template_lines(template: Template) -> list[str]:
    item = template.item
    lines = [f"{item.id} v{template.version}: {item.title}",
             f"Formula {template.formula_name} ({template.formula.artifact}), language "
             f"{template.language}" + (f", platform {template.platform}" if template.platform
                                       else "")]
    if template.layout_language:
        lines.append(template.layout_language.rule())
    if template.total_words:
        lines.append(f"Length: {template.total_words[0]}-{template.total_words[1]} words "
                     f"({template.formula.minutes[0] if template.formula.minutes else 0}-"
                     f"{template.formula.minutes[1] if template.formula.minutes else 0} min)")
    for spec in template.formula.sections:
        extra = (f"; one of {', '.join(spec.choices)}" if spec.choices else "") + (
            f'; ends with "{spec.ends_with}"' if spec.ends_with else "") + (
            f"; exactly {spec.lines} lines" if spec.lines else "") + (
            f", at most {spec.line_words} words each" if spec.line_words else "") + (
            f"; one of {', '.join(spec.line_choices)} per line" if spec.line_choices else "") + (
            "; in capitals" if spec.uppercase else "") + (
            f"; starts with {' / '.join(spec.prefixes)}" if spec.prefixes else "") + (
            f"; mark {spec.highlights} word like *word*" if spec.highlights else "") + (
            "; each line starts with a verb" if spec.verb_first else "") + (
            "; no quotes" if spec.no_quotes else "") + (
            f"; in {spec.language.upper()}" if spec.language else "") + (
            "; optional" if spec.optional else "")
        lines.append(f"- {spec.key} ({spec.words[0]}-{spec.words[1]} words{extra}): {spec.what}")
    if template.formula.banned_terms:
        lines.append("No jargon: " + ", ".join(template.formula.banned_terms))
    if template.rules:
        lines.append("Platform rules: " + json.dumps(
            template.rules.model_dump(by_alias=True, exclude_none=True)))
    lines.append(f"Claims ({len(template.claims)}):" if template.claims else
                 "Claims: none — research is thin; add sources first (research this link …).")
    lines += [f"  {c.id} [{c.label}, {c.status}] {c.text} ({', '.join(c.source_refs)})"
              for c in template.claims]
    if template.feedback:
        lines.append(f"Feedback for v{template.version}: {template.feedback}")
    lines.append(f"Write the JSON (`--json` skeleton) to a draft file, then `uv run ca script save "
                 f"{item.id} <file>`; it is stored in {template.stores_in.as_posix()}.")
    return lines
