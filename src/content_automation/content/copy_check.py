"""The copy of social graphics (2026-10-21): the free copy check, the copy review and its gate.

Rules: config/copy_rules.json (audience, angles, jargon, category rules, rubric, the CTA list
mapped to verified services); examples: brand/copy_examples.json (the approved references,
verbatim). Every graphic with a design direction (post, ad, carousel) carries a copyPlan in
brief.json: the reader angle, 3 scored headline options (the best is the headline) and the
visual concept (scene + 2-4 callouts).

- copy_problems: headline length and no jargon in it, the reader address of the category
  ("Sie"/"Ihr" or "du"/"dein"), the body length (jargon in it only when explained), 3-4 chips
  where the layout has chips (Roman: 3 and a full body line), the CTA from the category's list
  and fit for the brief's service, the copy plan; a carousel in sentence case, one idea per
  slide, the last slide asking for engagement. Free and offline.
- review_lines: the compact copy review Codex shows (`ca content copy`, `ca calendar copy`).
  A failing item is rewritten once (copy_review.json counts the failed versions); a second
  failure stops it: never sent to image generation.
- approve / approval_problem: the copy gate. The approved version (a digest of every graphic's
  copy and copy plan) is saved in copy_review.json; a paid build of a graphic that still needs
  an image refuses copy that is not approved or changed since.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from content_automation.content.brief import ContentBrief, CopyPlan, ImageSlot
from content_automation.content.directions import DirectionCatalog, DirectionError, Layout
from content_automation.content.relevance import INSIGHT_ONLY
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.references.services import ServiceCatalog

RULES_FILE = Path("config/copy_rules.json")
EXAMPLES_FILE = Path("brand/copy_examples.json")
REVIEW_FILE = "copy_review.json"  # in the package folder: failed versions, the approved one
SLOTS = ("post", "ad", "carousel")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FORMAL = re.compile(r"\b(?:Sie|Ihr|Ihre|Ihren|Ihrem|Ihrer|Ihres|Ihnen)\b")
_FORMAL_CAPS = re.compile(r"\b(?:SIE|IHR|IHRE|IHREN|IHREM|IHRER|IHRES|IHNEN)\b")
_INFORMAL = re.compile(r"\b(?:du|dein|deine|deinen|deinem|deiner|deines|dir|dich)\b",
                       re.IGNORECASE)
_ENGAGE = re.compile(r"\?|speicher|teil|kommentier|folg", re.IGNORECASE)


class CopyError(ValueError):
    """The copy cannot be approved (it fails the copy check) or the rules cannot be read."""


def _resolve(path: Path) -> Path:
    if not path.is_absolute() and not path.exists() and (_PROJECT_ROOT / path).exists():
        return _PROJECT_ROOT / path
    return path


@lru_cache(maxsize=4)
def _json(path: Path) -> dict[str, Any]:
    data = json.loads(_resolve(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CopyError(f"{path} must be a JSON object")
    return data


def load_rules(path: Path = RULES_FILE) -> dict[str, Any]:
    return _json(path)


def load_examples(path: Path = EXAMPLES_FILE) -> dict[str, Any]:
    return _json(path)


def help_block(category: str, roman: bool = False) -> dict[str, Any]:
    """The copy rules and the category's few-shot examples for brief.template.json _help."""
    rules = load_rules()
    rule = rules["categories"].get(category, {})
    examples = [item for item in load_examples()["examples"]
                if item["category"] == category or category in item.get("alsoFor", [])]
    block: dict[str, Any] = {
        "audience": rules["audience"],
        "angle": "First turn the topic into the reader's angle (copyPlan.angle): "
                 + " / ".join(rules["angles"].values()),
        "category": rule,
        "steps": ("Write 3 headline options (copyPlan.headlineOptions) with the patterns and "
                  "examples below, score each with the rubric (one point per criterion, 0-6), "
                  "keep the best as the copy's headline; then the body, the chips, the CTA and "
                  "copyPlan.visual (one concrete scene showing the benefit, 2-4 callout "
                  "labels) to match it; copy.illustration describes that scene."),
        "rubric": rules["rubric"],
        "jargon": ("never in a headline or a chip; in the body only explained in plain words: "
                   + ", ".join(rules["jargon"])),
        "patterns": load_examples()["patterns"],
        "examples": examples,
        "weak": load_examples().get("weak", []),
    }
    if roman:
        block["roman"] = rules["roman"]["_note"]
    return block


def plan_template(carousel: bool = False) -> dict[str, Any]:
    """The copyPlan skeleton of brief.template.json (help_block says how to fill it)."""
    patterns = " | ".join(load_examples()["patterns"])
    options = [{"text": f"<headline option {number}>", "pattern": f"<{patterns}>",
                "score": "<0-6: one point per rubric criterion>",
                "why": "<the rubric points it misses>"} for number in (1, 2, 3)]
    callouts = (["<optional German label>"] if carousel else
                [f"<German callout {number}: what the scene shows>" for number in (1, 2, 3)])
    return {"topicType": "<news | service>",
            "angle": "<what this means for the reader's business and what to do (news) / the "
                     "pain it removes and the gain (service)>",
            "headlineOptions": options,
            "visual": {"scene": "<the benefit in action: one concrete scene, in English (copy."
                                "illustration is written from it)>", "callouts": callouts}}


# --- The copy of a graphic ---------------------------------------------------------------------


def _lines(value: object) -> list[str]:
    from content_automation.workflows.design_render import plain

    items = value if isinstance(value, list) else [value]
    return [plain(str(item)).strip() for item in items if isinstance(item, str) and item.strip()]


def _text(copy: dict[str, Any], name: str | None) -> str:
    return " ".join(_lines(copy.get(name))) if name else ""


@dataclass
class _Fields:
    headline: str | None = None
    body: str | None = None
    cta: str | None = None
    chips: str | None = None


def _fields(layout: Layout) -> _Fields:
    """Which copy field is the headline, the body, the CTA and the chips in this layout."""
    found = _Fields()
    for zone in layout.zones.values():
        if zone.kind == "text" and zone.field:
            if zone.role == "headline" and found.headline is None:
                found.headline = zone.field
            elif zone.role in ("sub", "body") and found.body is None:
                found.body = zone.field
            elif zone.role == "cta":
                found.cta = zone.field
        elif zone.kind == "icons" and zone.field and zone.style != "engagement":
            found.chips = zone.field
    return found


@dataclass
class Page:
    """One image of a graphic (a post or ad, or one carousel slide) as the reader sees it."""

    role: str | None
    headline: str
    body: str
    chips: list[str]
    cta: str
    fields: _Fields


@dataclass
class CopyItem:
    part: str  # post | ad | carousel
    direction: str
    category: str
    roman: bool
    plan: CopyPlan | None
    pages: list[Page] = field(default_factory=list)

    @property
    def headline(self) -> str:
        return self.pages[0].headline if self.pages else ""


def copy_items(brief: ContentBrief, catalog: DirectionCatalog) -> list[CopyItem]:
    """Every graphic of the brief with a design direction, field by field."""
    from content_automation.workflows.direction_job import direction_layout

    items: list[CopyItem] = []
    for part in SLOTS:
        slot: ImageSlot | None = getattr(brief, part)
        if slot is None or not slot.direction:
            continue
        try:
            direction = catalog.get(slot.direction)
        except DirectionError:
            continue  # reported by the direction check
        item = CopyItem(part, direction.id, direction.category, direction.roman, slot.copy_plan)
        pages: list[tuple[str | None, dict[str, Any]]] = (
            [(slide.direction_role, dict(slide.copy_text)) for slide in slot.slides]
            if part == "carousel" else [(None, dict(slot.copy_text))])
        for role, copy in pages:
            try:
                _, layout = direction_layout(direction, platform=brief.platform, seed=brief.topic,
                                             role=role)
            except DirectionError:
                continue
            names = _fields(layout)
            item.pages.append(Page(role, _text(copy, names.headline), _text(copy, names.body),
                                   _lines(copy.get(names.chips)) if names.chips else [],
                                   _text(copy, names.cta), names))
        items.append(item)
    return items


# --- The copy check ----------------------------------------------------------------------------


def _words(text: str) -> int:
    return len(re.findall(r"[\wÄÖÜäöüß/-]+", text))


def _jargon(text: str, terms: list[str]) -> list[str]:
    """The jargon terms in a text (an acronym such as API only in capitals: "Dom" is no DOM)."""
    return [term for term in terms
            if re.search(rf"(?<![\w-]){re.escape(term)}(?:s|e|en|n|er|ern|ing)?(?![\w])", text,
                         0 if term.isupper() else re.IGNORECASE)]


def _unexplained(text: str, terms: list[str], markers: list[str]) -> list[str]:
    """Jargon in the body without a plain explanation after it ("(...)", " – ", "also" ...)."""
    found = []
    for term in _jargon(text, terms):
        hit = re.search(rf"(?<![\w-]){re.escape(term)}", text,
                        0 if term.isupper() else re.IGNORECASE)
        rest = text[hit.end():] if hit else ""
        if not any(marker in rest for marker in markers):
            found.append(term)
    return found


def _same(first: str, second: str) -> bool:
    return " ".join(first.casefold().split()) == " ".join(second.casefold().split())


def service_id(brief: ContentBrief, services: ServiceCatalog | None) -> str | None:
    """The verified service the brief names (None: insight-only or unknown)."""
    if services is None or brief.service == INSIGHT_ONLY:
        return None
    for service in services.services:
        if brief.service in (service.id, service.name, service.name_de):
            return service.id
    return None


def item_problems(item: CopyItem, brief: ContentBrief,
                  services: ServiceCatalog | None = None) -> list[str]:
    """The copy check of one graphic (each problem names where it is)."""
    rules = load_rules()
    rule = rules["categories"].get(item.category)
    if rule is None or not item.pages:
        return []
    where = f"[copy] {item.part} ({item.direction})"
    jargon, markers = list(rules["jargon"]), list(rules["explainedBy"])
    chips_rule, roman = rules["chips"], rules["roman"]
    problems: list[str] = []
    carousel = item.part == "carousel"
    for number, page in enumerate(item.pages, start=1):
        at = f"{where}{f' slide {number}' if carousel else ''}"
        if page.fields.headline and not page.headline:
            problems.append(f"{at}: write the headline")
        if _words(page.headline) > int(rule["headlineMaxWords"]):
            problems.append(f'{at}: headline "{page.headline}" has {_words(page.headline)} '
                            f"words (at most {rule['headlineMaxWords']})")
        if found := _jargon(page.headline, jargon):
            problems.append(f"{at}: jargon in the headline ({', '.join(found)}): say what it "
                            "means for the reader's business, in plain words")
        if (carousel and rule.get("sentenceCase") and sum(c.isalpha() for c in page.headline) > 3
                and page.headline == page.headline.upper()):
            problems.append(f"{at}: carousel headlines are in sentence case, not capitals")
        if _words(page.body) > int(rule["bodyMaxWords"]):
            problems.append(f'{at}: body "{page.body}" has {_words(page.body)} words (at most '
                            f"{rule['bodyMaxWords']}: one concrete benefit in one sentence)")
        if found := _unexplained(page.body, jargon, markers):
            problems.append(f"{at}: jargon in the body ({', '.join(found)}): explain it in plain "
                            "words right after it or leave it out")
        if item.roman and page.fields.body and _words(page.body) < int(roman["bodyMinWords"]):
            problems.append(f"{at}: a Roman post needs a full body line under the headline (at "
                            f"least {roman['bodyMinWords']} words), not a thin one-liner")
        if item.roman and not page.fields.chips:
            problems.append(f"{at}: a Roman post shows {roman['chips']} benefit chips; this "
                            "layout has no chips zone")
        if page.fields.chips:
            low = int(roman["chips"]) if item.roman else int(chips_rule["min"])
            high = int(roman["chips"]) if item.roman else int(chips_rule["max"])
            if not low <= len(page.chips) <= high:
                problems.append(f"{at}: {len(page.chips)} chip(s); write {low}"
                                f"{f'-{high}' if high != low else ''} short benefit labels")
            for chip in page.chips:
                if _words(chip) > int(chips_rule["maxWords"]) or _jargon(chip, jargon):
                    problems.append(f'{at}: chip "{chip}": at most {chips_rule["maxWords"]} '
                                    "plain words (verb + noun or one noun), no jargon")
        problems += _cta_problems(at, item.category, page, rules, brief, services)
    texts = " ".join(f"{page.headline} {page.body} {' '.join(page.chips)} {page.cta}"
                     for page in item.pages)
    if rule["address"] == "Sie":
        first = item.pages[0]
        if not (_FORMAL.search(f"{first.headline} {first.body}")
                or _FORMAL_CAPS.search(first.headline)):
            problems.append(f'{where}: speak to the reader with "Sie"/"Ihr" in the headline or '
                            "the body (what it means for their business)")
        if found_du := _INFORMAL.search(texts):
            problems.append(f'{where}: "{found_du.group(0)}": this category says "Sie", not "du"')
    elif not _INFORMAL.search(texts):
        problems.append(f'{where}: a carousel speaks to the reader with "du"/"dein" (at least '
                        "once in the set)")
    if carousel and len(item.pages) > 1:
        last = item.pages[-1]
        if not _ENGAGE.search(f"{last.headline} {last.body}"):
            problems.append(f"{where}: the last slide asks for engagement (a question to "
                            "comment on, or save/share)")
    if item.category == "facebook_ad" and brief.service == INSIGHT_ONLY:
        problems.append(f"{where}: an ad needs an offer: name the verified service it sells")
    return problems + _plan_problems(where, item, rules)


def _cta_problems(at: str, category: str, page: Page, rules: dict[str, Any],
                  brief: ContentBrief, services: ServiceCatalog | None) -> list[str]:
    rule = rules["categories"][category]
    if not page.fields.cta:
        return []
    if not page.cta:
        return [f"{at}: an ad needs its CTA ({', '.join(rule['ctas'])})"] if rule.get(
            "ctaRequired") else []
    if page.cta not in rule["ctas"]:
        return [f'{at}: CTA "{page.cta}" is not on the {category} list (a low-friction offer '
                f"tied to a service): {', '.join(rule['ctas'])}"]
    entry = rules["ctas"].get(page.cta, {})
    if brief.service == INSIGHT_ONLY:
        return [] if entry.get("insightOnly") else [
            f'{at}: CTA "{page.cta}" sells a service; an insight-only post uses '
            + ", ".join(name for name, value in rules["ctas"].items()
                        if value.get("insightOnly") and name in rule["ctas"])]
    fits = entry.get("services", "any")
    wanted = service_id(brief, services)
    if fits != "any" and wanted is not None and wanted not in fits:
        return [f'{at}: CTA "{page.cta}" does not fit the service {brief.service} '
                f"(it fits {', '.join(fits)})"]
    return []


def _plan_problems(where: str, item: CopyItem, rules: dict[str, Any]) -> list[str]:
    plan = item.plan
    if plan is None:
        return [f"{where}: add copyPlan (the reader angle, 3 scored headline options, the visual "
                "concept; brief.template.json _help.copyRules)"]
    problems = []
    texts = [option.text for option in plan.headline_options]
    if len({" ".join(text.casefold().split()) for text in texts}) < len(texts):
        problems.append(f"{where}: the 3 headline options must differ")
    chosen = next((option for option in plan.headline_options
                   if _same(option.text, item.headline)), None)
    best = max(option.score for option in plan.headline_options)
    if chosen is None:
        problems.append(f'{where}: the headline "{item.headline}" is not one of the 3 options')
    elif chosen.score < best:
        problems.append(f"{where}: the headline scores {chosen.score}; use the best option "
                        f"({best})")
    elif chosen.score < int(rules["minScore"]):
        problems.append(f"{where}: the best headline scores {chosen.score} of 6 (at least "
                        f"{rules['minScore']}): write better options")
    callouts = rules["visualCallouts"]
    low = int(callouts["carouselMin"] if item.part == "carousel" else callouts["min"])
    if not low <= len(plan.visual.callouts) <= int(callouts["max"]):
        problems.append(f"{where}: copyPlan.visual has {len(plan.visual.callouts)} callout(s); "
                        f"write {low}-{callouts['max']} short labels of what the scene shows")
    return problems


def copy_problems(brief: ContentBrief, catalog: DirectionCatalog,
                  services: ServiceCatalog | None = None) -> list[str]:
    problems: list[str] = []
    for item in copy_items(brief, catalog):
        problems += item_problems(item, brief, services)
    return problems


# --- The copy review and its gate --------------------------------------------------------------


def copy_digest(brief: ContentBrief) -> str:
    """The version of everything the copy review shows (copy, slides, copy plans)."""
    parts: dict[str, Any] = {}
    for part in SLOTS:
        slot: ImageSlot | None = getattr(brief, part)
        if slot is None or not slot.direction:
            continue
        parts[part] = {
            "direction": slot.direction, "copy": slot.copy_text,
            "plan": slot.copy_plan.model_dump(by_alias=True) if slot.copy_plan else None,
            "slides": [{"copy": slide.copy_text, "illustration": slide.illustration}
                       for slide in slot.slides]}
    text = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _state(folder: Path) -> dict[str, Any]:
    try:
        data = json.loads((folder / REVIEW_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(folder: Path, state: dict[str, Any]) -> None:
    atomic_write_text(folder / REVIEW_FILE, json.dumps(state, indent=2, ensure_ascii=False))


def is_approved(folder: Path, brief: ContentBrief) -> bool:
    return _state(folder).get("approved") == copy_digest(brief)


def approval_problem(folder: Path, brief: ContentBrief) -> str | None:
    """The copy gate: None when there is no direction graphic or its copy is approved."""
    if not any((slot := getattr(brief, part)) is not None and slot.direction for part in SLOTS):
        return None
    if is_approved(folder, brief):
        return None
    return (f'[copy] the copy is not approved (or changed since): show the copy review (uv run '
            f'ca content copy "{folder}") and wait for the user\'s ok; images are made only for '
            "approved copy")


def approve(folder: Path, brief: ContentBrief, problems: list[str]) -> str:
    """Record the user's ok to this version of the copy (refused while the copy check fails)."""
    if problems:
        raise CopyError(f"{folder.name}: the copy fails the copy check ({len(problems)} "
                        "problem(s)); it cannot be approved")
    state = _state(folder)
    digest = copy_digest(brief)
    state.update({"approved": digest, "approvedAt": datetime.now(UTC).isoformat(
        timespec="seconds"), "failed": []})
    _save(folder, state)
    return digest


def review_lines(folder: Path, brief: ContentBrief, catalog: DirectionCatalog,
                 services: ServiceCatalog | None = None, *,
                 retry: bool = False) -> tuple[list[str], list[str]]:
    """(the compact copy review, its copy problems). A failing version is counted: the first
    gets one rewrite, a second stops the item (retry: the user asked for another rewrite)."""
    from content_automation.workflows.design_render import cta_icon

    lines: list[str] = []
    problems: list[str] = []
    approved = is_approved(folder, brief)
    for item in copy_items(brief, catalog):
        found = item_problems(item, brief, services)
        problems += found
        rule = load_rules()["categories"].get(item.category, {})
        verdict = f"{len(found)} problem(s)" if found else "passed"
        lines.append(f"[{item.part}] {item.direction} {item.category}"
                     f"{' (Roman)' if item.roman else ''} · {rule.get('address', '')} · copy "
                     f"check {verdict} · {'approved' if approved else 'waiting for ok'}")
        plan = item.plan
        if plan is not None:
            lines.append(f"  Angle ({plan.topic_type}): {plan.angle}")
        for number, page in enumerate(item.pages, start=1):
            prefix = f"  {number} {page.role}: " if item.part == "carousel" else "  "
            option = next((o for o in plan.headline_options if _same(o.text, page.headline)),
                          None) if plan is not None and number == 1 else None
            score = f" ({option.pattern}, {option.score}/6)" if option is not None else ""
            lines.append(f"{prefix}Headline: {page.headline or '-'}{score}")
            if page.body:
                lines.append(f"{prefix}Body: {page.body}")
            if page.chips:
                lines.append(f"{prefix}Chips: {' · '.join(page.chips)}")
            if page.cta:
                icon = "calendar" if cta_icon(page.cta)[0] == "calendar" else "circle arrow"
                lines.append(f"{prefix}CTA: {page.cta} ({icon})")
        if plan is not None:
            others = [o for o in plan.headline_options if not _same(o.text, item.headline)]
            if others:
                lines.append("  Other headlines: " + " | ".join(
                    f'"{o.text}" ({o.score}/6)' for o in others))
            lines.append(f"  Visual: {plan.visual.scene}"
                         + (f" · callouts: {' · '.join(plan.visual.callouts)}"
                            if plan.visual.callouts else ""))
        lines += [f"  ! {problem.removeprefix('[copy] ')}" for problem in found]
    if problems:
        state = _state(folder)
        digest = copy_digest(brief)
        failed = [] if retry else list(state.get("failed", []))
        if digest not in failed:
            failed.append(digest)
        state["failed"] = failed
        _save(folder, state)
        lines.append("REWRITE ONCE: fix the problems above in brief.json, then run the copy "
                     "review again." if len(failed) < 2 else
                     "STOPPED: the copy still fails after its one rewrite; it is not sent to "
                     "image generation. Show the user the problems and ask for their words "
                     "(their rewrite request: run again with --retry).")
    return lines, problems


def package_review(folder: Path, settings: Settings, *, approve_it: bool = False,
                   retry: bool = False) -> tuple[list[str], list[str]]:
    """The copy review of one package; approve_it (only after the user's ok): the version is
    recorded and logged as the copy decision of each of its items."""
    from content_automation.content.brief import parse_brief
    from content_automation.content.directions import load_directions
    from content_automation.content.package import BRIEF_FILE, resolve_package_folder
    from content_automation.references.services import ServicesError, load_services
    from content_automation.registry import runtime

    folder = resolve_package_folder(folder)
    brief = parse_brief(folder / BRIEF_FILE)
    try:
        services: ServiceCatalog | None = load_services(settings.services_file)
    except ServicesError:
        services = None
    lines, problems = review_lines(folder, brief, load_directions(), services, retry=retry)
    if not lines:
        return ["No graphic with a design direction in brief.json: nothing to review."], []
    if approve_it:
        digest = approve(folder, brief, problems)
        lines.append(f"Copy approved ({digest}): its images may be made after the dry run and "
                     "the user's ok. A change to the copy needs a new review.")
        for item_id in runtime.package_items(folder).values():
            runtime.log(item_id, "decision", {"gate": "copy", "decision": "approved",
                                              "digest": digest})
    return lines, problems


def week_review(settings: Settings, label: str, *, approve_rows: str | None = None,
                retry: bool = False) -> tuple[list[str], list[str]]:
    """The copy review of a calendar week: every Approved row with a package and brief.json.
    approve_rows: "all" or row numbers / BG IDs ("1,3" or "BG-125 BG-126"); a row whose copy
    fails the check is never approved. Returns the lines and the rows not passed or approved."""
    from content_automation.content.brief import BriefError
    from content_automation.content.calendar import APPROVED_STATES, calendar_path, read_view

    wanted = {part.strip().upper() for part in re.split(r"[,\s]+", approve_rows or "")
              if part.strip()}
    lines: list[str] = []
    open_rows: list[str] = []
    for row in read_view(calendar_path(settings, label)):
        if row["Status"] not in APPROVED_STATES or not row["Package"]:
            continue
        name = f"Row {row['Row']} {row['BG ID'] or ''} ({row['Planned date']}, " \
               f"{row['Content type']}): {row['Topic']}"
        chosen = "ALL" in wanted or row["Row"] in wanted or (row["BG ID"] or "").upper() in wanted
        lines.append(name)
        try:
            found, problems = package_review(Path(row["Package"]), settings,
                                             approve_it=chosen, retry=retry)
        except (BriefError, CopyError) as error:
            lines.append(f"  ! {error}")
            open_rows.append(name)
            continue
        lines += found
        if problems or (wanted and not chosen):
            open_rows.append(name)
    if not lines:
        lines.append(f"{label}: no Approved row with a package yet (run generate approved "
                     "first: stage 1 and brief.json).")
    return lines, open_rows


__all__ = ["CopyError", "CopyItem", "Page", "REVIEW_FILE", "RULES_FILE", "approval_problem",
           "approve", "copy_digest", "copy_items", "copy_problems", "help_block",
           "is_approved", "item_problems", "load_examples", "load_rules", "package_review",
           "plan_template", "review_lines", "service_id", "week_review"]
