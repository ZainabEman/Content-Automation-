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

Phase 1 of GERMAN_CONTENT_AND_IMAGE_WORKFLOW_PRD.md (2026-10-22, german-editorial skill): the
copyPlan also carries the editorial brief (proof with its source) and the piece review (the
pieceRubric, 0-2 per criterion); the caption and the ad texts get the same "Sie"/"du" rule as the
graphic. The copy review adds (free, offline): the claims check ("unbelegte Aussage" for a number,
year, euro amount, organisation or study statement missing from the evidence), the German check
with the category's address, the layout fit (the dry run's stand-in drawing, the ad included) and
warnings (long sentences, Nominalstil, near-identical copy of one topic, a headline pattern used
too often in a week). Warnings never block; thresholds live in config/copy_rules.json.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Any

from content_automation.content.brief import Caption, ContentBrief, CopyPlan, ImageSlot
from content_automation.content.directions import DirectionCatalog, DirectionError, Layout
from content_automation.content.german import check_text
from content_automation.content.german import load_rules as german_rules
from content_automation.content.relevance import INSIGHT_ONLY
from content_automation.content.topic_pool import similarity
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
# The formal address inside a sentence (at its start "Sie" may be "they"): wrong in a "du" item
_FORMAL_INNER = re.compile(r"(?<![.!?:]\s)(?<!^)\b(?:Sie|Ihnen|Ihr|Ihre|Ihren|Ihrem|Ihrer|Ihres)\b")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_INNER_CAPS = re.compile(r"\b[A-Z][a-z]+[A-Z]\w*")  # OpenAI, DeepSeek, HubSpot: a named company
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
# What the evidence must mention before the copy may speak of a study (DE and EN sources)
_STUDY_SOURCE = re.compile(r"studie|study|studies|survey|umfrage|paper|untersuchung|forscher"
                           r"|researchers", re.IGNORECASE)


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
        "skill": ("Follow .agents/skills/german-editorial: editorial brief, draft, self-review, "
                  "the copy check (uv run ca content copy), one rewrite."),
        "audience": rules["audience"],
        "editorialBrief": rules["editorialBrief"]["_note"],
        "angle": "First turn the topic into the reader's angle (copyPlan.angle): "
                 + " / ".join(rules["angles"].values()),
        "category": rule,
        "steps": ("Write 3 headline options (copyPlan.headlineOptions) with the patterns and "
                  "examples below, score each with the rubric (one point per criterion, 0-6), "
                  "keep the best as the copy's headline; then the body, the chips, the CTA and "
                  "copyPlan.visual (one concrete scene showing the benefit, 2-4 callout "
                  "labels) to match it; copy.illustration describes that scene. Then score the "
                  "whole piece, graphic and caption (copyPlan.review, pieceRubric)."),
        "rubric": rules["rubric"],
        "pieceRubric": rules["pieceRubric"],
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
    criteria = load_rules()["pieceRubric"]["criteria"]
    return {"topicType": "<news | service>",
            "angle": "<what this means for the reader's business and what to do (news) / the "
                     "pain it removes and the gain (service)>",
            "editorial": {
                "audience": "<which German business reader, e.g. Inhaber eines Handwerksbetriebs "
                            "mit 20 Mitarbeitenden>",
                "problem": "<the situation in the reader's own words>",
                "coreIdea": "<the one idea, one sentence>",
                "proof": {"fact": "<the source fact (or verified service fact) the piece stands "
                                  "on>",
                          "source": "<a cited article ID | a research.md link | proof.md | "
                                    "service:<verified service id>>"},
                "objection": "<the reader's likely doubt>",
                "action": "<what the reader should do next>"},
            "headlineOptions": options,
            "visual": {"scene": "<the benefit in action: one concrete scene, in English (copy."
                                "illustration is written from it)>", "callouts": callouts},
            "review": {"scores": {name: "<0-2>" for name in criteria},
                       "why": "<what keeps a score below 2>"}}


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


def item_caption(brief: ContentBrief, item: CopyItem) -> Caption | None:
    """The caption posted with this graphic (captions.<category>; an old brief: caption)."""
    return brief.captions.get(item.category) or (brief.caption if not brief.captions else None)


def caption_text(brief: ContentBrief, item: CopyItem) -> str:
    caption = item_caption(brief, item)
    if caption is None:
        return ""
    return "\n".join([caption.hook, *caption.takeaways, caption.question,
                      caption.closing_de or ""]).strip()


def item_texts(item: CopyItem, brief: ContentBrief) -> list[tuple[str, str]]:
    """(where, text) of everything the reader of this piece sees: the graphic (each slide), the
    caption with its CTA line and a Facebook ad's own texts."""
    texts: list[tuple[str, str]] = []
    for number, page in enumerate(item.pages, start=1):
        at = f"slide {number}" if item.part == "carousel" else "graphic"
        texts += [(f"{at} headline", page.headline), (f"{at} body", page.body),
                  *((f"{at} chip", chip) for chip in page.chips), (f"{at} cta", page.cta)]
    caption = item_caption(brief, item)
    if caption is not None:
        texts += [("caption hook", caption.hook),
                  *(("caption takeaway", line) for line in caption.takeaways),
                  ("caption question", caption.question),
                  ("caption closing", caption.closing_de or ""), ("caption cta", brief.cta)]
    slot: ImageSlot | None = getattr(brief, item.part)
    if slot is not None and slot.ad_fields is not None:
        texts += [("ad primary text", slot.ad_fields.primary_text),
                  ("ad headline", slot.ad_fields.headline),
                  ("ad description", slot.ad_fields.description)]
    return [(where, text) for where, text in texts if text and text.strip()]


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
        middle = carousel and 1 < number < len(item.pages)  # a carousel's point slides
        body_max = int(rule.get("bodyMaxWordsBySlide", {}).get(page.role or "",
                                                               rule["bodyMaxWords"])
                       if middle else rule["bodyMaxWords"])
        if _words(page.body) > body_max:
            problems.append(f'{at}: body "{page.body}" has {_words(page.body)} words (at most '
                            f"{body_max}: " + ("one point, in short lines)" if middle else
                                               "one concrete benefit in one sentence)"))
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
    piece = item_texts(item, brief)  # 2026-10-22: the caption and the ad texts too
    if rule["address"] == "Sie":
        first = item.pages[0]
        if not (_FORMAL.search(f"{first.headline} {first.body}")
                or _FORMAL_CAPS.search(first.headline)):
            problems.append(f'{where}: speak to the reader with "Sie"/"Ihr" in the headline or '
                            "the body (what it means for their business)")
        wrong = [f'{at} "{hit.group(0)}"' for at, text in piece
                 if (hit := _INFORMAL.search(text))]
    else:
        if not _INFORMAL.search(texts):
            problems.append(f'{where}: a carousel speaks to the reader with "du"/"dein" (at '
                            "least once in the set)")
        wrong = [f'{at} "{hit.group(0)}"' for at, text in piece
                 if (hit := _FORMAL_INNER.search(text))]
    if wrong:
        other = "du" if rule["address"] == "Sie" else "Sie"
        problems.append(f'{where}: this category says "{rule["address"]}", not "{other}", in '
                        f"the graphic and the caption: {'; '.join(dict.fromkeys(wrong))}")
    if carousel and len(item.pages) > 1:
        last = item.pages[-1]
        if not _ENGAGE.search(f"{last.headline} {last.body}"):
            problems.append(f"{where}: the last slide asks for engagement (a question to "
                            "comment on, or save/share)")
    if item.category == "facebook_ad" and brief.service == INSIGHT_ONLY:
        problems.append(f"{where}: an ad needs an offer: name the verified service it sells")
    return problems + _plan_problems(where, item, rules, brief, services)


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


def _plan_problems(where: str, item: CopyItem, rules: dict[str, Any], brief: ContentBrief,
                   services: ServiceCatalog | None) -> list[str]:
    plan = item.plan
    if plan is None:
        return [f"{where}: add copyPlan (the editorial brief, the reader angle, 3 scored headline "
                "options, the visual concept, the piece review; brief.template.json "
                "_help.copyRules)"]
    problems = _editorial_problems(where, plan, brief, services)
    problems += _review_problems(where, plan, rules)
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


def proof_sources(brief: ContentBrief) -> set[str]:
    """The sources the editorial proof may name: the cited articles and the insights' sources."""
    return {*brief.source_article_ids, *(insight.source for insight in brief.insights)}


def _editorial_problems(where: str, plan: CopyPlan, brief: ContentBrief,
                        services: ServiceCatalog | None) -> list[str]:
    """P1-R1: the editorial brief exists and its proof names a source the brief can show."""
    editorial = plan.editorial
    if editorial is None:
        return [f"{where}: add copyPlan.editorial (audience, problem, coreIdea, proof with fact "
                "and source, objection, action), written before the copy (german-editorial "
                "references/editorial-brief.md)"]
    source = editorial.proof.source.strip()
    verified = {service.id for service in services.verified()} if services else None
    known = (source in proof_sources(brief) or source.startswith("http")
             or source in ("proof.md", "brand/proof.md")
             or (source.startswith("service:")
                 and (verified is None or source.removeprefix("service:") in verified)))
    if known:
        return []
    return [f'{where}: copyPlan.editorial.proof.source "{source}": name a cited article ID, a '
            "research.md link, proof.md or service:<verified service id>"]


def _review_problems(where: str, plan: CopyPlan, rules: dict[str, Any]) -> list[str]:
    """P1-R6: the piece review scores every pieceRubric criterion 0-2 and reaches the bar."""
    rubric = rules["pieceRubric"]
    criteria = list(rubric["criteria"])
    if plan.review is None:
        return [f"{where}: add copyPlan.review (score the whole piece 0-2 on: "
                f"{', '.join(criteria)}; german-editorial references/review-rubric.md)"]
    scores = plan.review.scores
    wrong = sorted({*(name for name in criteria if name not in scores),
                    *(name for name, value in scores.items()
                      if name not in criteria or not 0 <= value <= 2)})
    if wrong:
        return [f"{where}: copyPlan.review.scores: one score 0-2 for each of {', '.join(criteria)}"
                f" (wrong or missing: {', '.join(wrong)})"]
    total = sum(scores[name] for name in criteria)
    low = [name for name in criteria if scores[name] < int(rubric["minEach"])]
    short = [name for name in rubric["mustBeFull"] if scores[name] < 2]
    if total >= int(rubric["minTotal"]) and not low and not short:
        return []
    weak = ", ".join(f"{name} {scores[name]}" for name in criteria if scores[name] < 2)
    return [f"{where}: the piece review scores {total}/{2 * len(criteria)} (at least "
            f"{rubric['minTotal']}, none below {rubric['minEach']}, "
            f"{' and '.join(rubric['mustBeFull'])} at 2; low: {weak}): rewrite the piece"]


def review_total(plan: CopyPlan | None, rules: dict[str, Any]) -> str:
    """The piece review as the copy review shows it: "14/16 (specificity 1, hook 1)"."""
    if plan is None or plan.review is None:
        return "-"
    criteria = list(rules["pieceRubric"]["criteria"])
    scores = plan.review.scores
    total = sum(scores.get(name, 0) for name in criteria)
    weak = [f"{name} {scores.get(name, 0)}" for name in criteria if scores.get(name, 0) < 2]
    return f"{total}/{2 * len(criteria)}" + (f" ({', '.join(weak)})" if weak else "")


# --- The review checks: claims, German, fit, warnings (free, offline) --------------------------


def evidence_text(brief: ContentBrief, folder: Path | None = None,
                  settings: Settings | None = None,
                  services: ServiceCatalog | None = None) -> str:
    """Everything a claim may stand on: the editorial proofs, the insights, research.md and the
    cited articles, brand/proof.md and the verified services."""
    from content_automation.content.package import PROOF_FILE, RESEARCH_FILE
    from content_automation.research.store import find_article

    parts = [insight.text for insight in brief.insights]  # the facts, not their source IDs
    for part in SLOTS:
        slot: ImageSlot | None = getattr(brief, part)
        if slot is not None and slot.copy_plan is not None and slot.copy_plan.editorial:
            parts.append(slot.copy_plan.editorial.proof.fact)
    files = [folder / RESEARCH_FILE] if folder is not None else []
    if settings is not None:
        files.append(settings.company_file.parent / PROOF_FILE)
        for article_id in sorted(proof_sources(brief)):
            found = find_article(settings.research_dir, article_id)
            if found is not None:
                parts.append(f"{found.title} {found.summary} {found.content}")
    parts += [path.read_text(encoding="utf-8") for path in files if path.is_file()]
    for service in services.verified() if services else []:
        parts.append(" ".join([service.name, service.name_de, service.what_it_does,
                               *service.problems_solved, *service.use_cases, *service.proof]))
    return "\n".join(parts)


def claim_problems(where: str, texts: list[tuple[str, str]], evidence: str,
                   rules: dict[str, Any]) -> list[str]:
    """P1-R5: numbers, years, euro amounts, percentages, organisations and study statements of
    the piece that the evidence does not contain ("unbelegte Aussage")."""
    claims = rules["claims"]
    known = evidence.casefold()
    numbers = set(_NUMBER.findall(evidence))
    after = re.compile(r"\s*(?:" + "|".join(re.escape(word) for word in
                                           [*claims["scenarioUnits"], *claims["ownCounts"]])
                       + r")\b|/7\b")
    study = re.compile(r"(?<![\wäöüß])(?:" + "|".join(re.escape(word) for word in
                                                     claims["studyWords"])
                       + r")(?![\wäöüß])", re.IGNORECASE)
    allowed = {name.casefold() for name in claims["allowNames"]}
    # 2026-10-22: written numbers ("vier Tools") and shares ("die Hälfte") are claims too; the
    # evidence may hold the digits, the German word or the English one ("four")
    evidence_words = set(re.findall(r"[a-zäöüß]+", evidence.lower()))  # lower keeps "ß"
    values = {int(number) for number in numbers if number.isdigit()}
    for table in (claims["numberWords"], claims["englishNumberWords"]):
        values |= {int(value) for word, value in table.items() if word in evidence_words}
    spoken = re.compile(r"(?<![\wäöüß])(" + "|".join(sorted(claims["numberWords"], key=len,
                                                           reverse=True))
                        + r")(?![\wäöüß])", re.IGNORECASE)
    shares = {word: re.compile(r"(?<![\wäöüß])" + (r"jede[rs]?\s+zweite[nrs]?" if word ==
                                                   "jede zweite" else re.escape(word) + r"\w*")
                               + r"(?![\wäöüß])", re.IGNORECASE)
              for word in claims["shareWords"]}

    def named(name: str) -> bool:  # "DeepSeeks" (genitive) is DeepSeek
        low = name.casefold()
        return low in allowed or low in known or (low.endswith("s") and low[:-1] in known)

    def marked(marker: str) -> bool:
        return marker in numbers or re.search(
            rf"(?<![\wäöüß]){re.escape(marker)}(?![\wäöüß])", known) is not None

    found: list[str] = []
    for at, text in texts:
        for match in _NUMBER.finditer(text):
            if after.match(text, match.end()) or text[:match.start()].endswith("24/"):
                continue  # a scenario timing, a count of the post's own points, 24/7
            number = match.group(0)  # "26,2" in German is "26.2" in an English source
            if not {number, number.replace(",", "."), number.replace(".", ",")} & numbers:
                found.append(f'{at} "{number}"')
        for match in spoken.finditer(text):
            if after.match(text, match.end()):
                continue
            if int(claims["numberWords"][match.group(1).lower()]) not in values:
                found.append(f'{at} "{match.group(1)}"')
        for word, pattern in shares.items():
            if (hit := pattern.search(text)) and not any(
                    marked(marker) for marker in claims["shareWords"][word]):
                found.append(f'{at} "{hit.group(0)}"')
        names = {match.group(0) for match in _INNER_CAPS.finditer(text)}
        names |= {name for name in claims["organisations"]
                  if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w])", text)}
        found += [f'{at} "{name}"' for name in sorted(names) if not named(name)]
        for match in study.finditer(text):
            if match.group(0).casefold() == "laut":
                who = re.match(r"\s+(?:der |die |dem |des )?([A-ZÄÖÜ][\w-]+)",
                               text[match.end():])
                if who and not named(who.group(1)):
                    found.append(f'{at} "laut {who.group(1)}"')
            elif not _STUDY_SOURCE.search(evidence):
                found.append(f'{at} "{match.group(0)}"')
    if not found:
        return []
    return [f"{where}: unbelegte Aussage: {'; '.join(dict.fromkeys(found))}: not in the editorial "
            "proof, the insights, the research or the verified services; cite it in "
            "copyPlan.editorial.proof or leave it out"]


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCES.split(text) if part.strip()]


def german_findings(where: str, item: CopyItem, texts: list[tuple[str, str]]
                    ) -> tuple[list[str], list[str]]:
    """The free German check (config/german_quality.json) with the category's address: errors
    block, warnings are shown."""
    address = load_rules()["categories"].get(item.category, {}).get("address", "Sie")
    rules = replace(german_rules(), address=address)
    problems: list[str] = []
    warnings: list[str] = []
    for at, text in texts:
        report = check_text(text, f"{where} {at}", rules)
        problems += report.errors
        # the address itself is a problem of the copy check (item_problems), not repeated here
        warnings += [line for line in report.warnings if "the default address" not in line]
    return problems, warnings


def style_warnings(where: str, texts: list[tuple[str, str]], rules: dict[str, Any]) -> list[str]:
    """P1-R2/R7: long caption sentences and noun chains (Nominalstil); never blocking."""
    style = rules["style"]
    suffixes = tuple(style["nounSuffixes"])
    warnings: list[str] = []
    for at, text in texts:
        for sentence in _sentences(text):
            words = re.findall(r"[\wÄÖÜäöüß-]+", sentence)
            if at.startswith(("caption", "ad primary")) and len(words) > int(
                    style["sentenceMaxWords"]):
                warnings.append(f"{where} {at}: {len(words)} words in one sentence (aim for at "
                                f"most {style['sentenceMaxWords']}): split it")
            chain = [word for word in words
                     if word[:1].isupper() and len(word) > 5 and word.lower().endswith(suffixes)]
            if len(chain) >= int(style["nounChainMin"]):
                warnings.append(f"{where} {at}: Nominalstil ({', '.join(chain)}): write the verb "
                                "(\"prüfen\", not \"die Durchführung einer Prüfung\")")
    return warnings


def near_duplicates(where: str, pieces: list[tuple[str, str, str]],
                    rules: dict[str, Any]) -> list[str]:
    """P1-R4: (label, headline, caption) of one topic on several platforms: near-identical
    headlines or captions are flagged (content/topic_pool.similarity)."""
    limit = float(rules["week"]["similarity"])
    warnings: list[str] = []
    for (first, head_a, text_a), (second, head_b, text_b) in combinations(pieces, 2):
        for kind, a, b in (("headline", head_a, head_b), ("caption", text_a, text_b)):
            if a and b and (score := similarity(a, b)) >= limit:
                warnings.append(f"{where}: {first} and {second} share a near-identical {kind} "
                                f"({score:.2f}): write platform-specific copy")
    return warnings


def caption_findings(brief: ContentBrief, settings: Settings) -> list[str]:
    """The dry run's own caption checks (content/quality.caption_problems: the word range, the
    LinkedIn hook line, specific takeaways, the offer in the CTA), shown in the copy review so the
    copy step fixes them, not the dry run."""
    from content_automation.content.deliverables import DeliverableError, load_deliverables
    from content_automation.content.quality import caption_problems
    from content_automation.references import load_company

    company = load_company(settings.company_file)
    offer = company.offer if company and brief.service != INSIGHT_ONLY else ""
    platforms: dict[str, str] = {}
    try:
        catalog = load_deliverables(settings.deliverables_file)
        platforms = {key: found.platform for key in brief.deliverables
                     if (found := catalog.deliverables.get(key)) is not None and found.platform}
    except DeliverableError:
        pass  # reported by the dry run
    return [f"[caption] {line}" for line in caption_problems(brief, offer, platforms)]


def chosen_pattern(item: CopyItem) -> str | None:
    """The pattern of the headline option the graphic uses."""
    if item.plan is None:
        return None
    return next((option.pattern for option in item.plan.headline_options
                 if _same(option.text, item.headline)), None)


def review_checks(item: CopyItem, brief: ContentBrief, *, evidence: str | None = None
                  ) -> tuple[list[str], list[str]]:
    """The copy review's own checks of one piece: (blocking problems, warnings)."""
    rules = load_rules()
    where = f"[copy] {item.part} ({item.direction})"
    texts = item_texts(item, brief)
    problems, warnings = german_findings(where, item, texts)
    if evidence is not None:
        problems += claim_problems(where, texts, evidence, rules)
    warnings += style_warnings(where, texts, rules)
    return problems, warnings


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
                       for slide in slot.slides],
            "adFields": slot.ad_fields.model_dump(by_alias=True) if slot.ad_fields else None}
    if parts:  # 2026-10-22: the review also checks the captions (P1-R4/R5)
        parts["captions"] = {key: caption.model_dump(by_alias=True)
                             for key, caption in brief.captions.items()}
        parts["caption"] = brief.caption.model_dump(by_alias=True) if brief.caption else None
        parts["cta"] = brief.cta
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
                 services: ServiceCatalog | None = None, *, retry: bool = False,
                 settings: Settings | None = None,
                 evidence: str | None = None) -> tuple[list[str], list[str]]:
    """(the compact copy review, its copy problems). A failing version is counted: the first
    gets one rewrite, a second stops the item (retry: the user asked for another rewrite).
    settings: also the layout fit (the dry run's stand-in drawing, the ad included); evidence:
    also the claims check. Warnings (~) are shown and never block."""
    from content_automation.content.direction_brief import direction_problems
    from content_automation.workflows.design_render import cta_icon

    rules = load_rules()
    lines: list[str] = []
    problems: list[str] = []
    approved = is_approved(folder, brief)
    items = copy_items(brief, catalog)
    captions = caption_findings(brief, settings) if settings is not None and items else []
    for number, item in enumerate(items):
        found = item_problems(item, brief, services)
        extra, warnings = review_checks(item, brief, evidence=evidence)
        found += extra
        if settings is not None:
            found += [f"[fit] {line}" for line in direction_problems(brief, catalog, settings,
                                                                     parts=(item.part,))]
        if number == 0:
            found += captions  # the package's captions, shown once
        problems += found
        rule = rules["categories"].get(item.category, {})
        verdict = f"{len(found)} problem(s)" if found else "passed"
        plan = item.plan
        lines.append(f"[{item.part}] {item.direction} {item.category}"
                     f"{' (Roman)' if item.roman else ''} · {rule.get('address', '')} · copy "
                     f"check {verdict} · review {review_total(plan, rules)} · "
                     f"{'approved' if approved else 'waiting for ok'}")
        if plan is not None and plan.editorial is not None:
            brief_of = plan.editorial
            lines.append(f"  Brief: {brief_of.audience} · problem: {brief_of.problem} · idea: "
                         f"{brief_of.core_idea}")
            lines.append(f"  Proof: {brief_of.proof.fact} ({brief_of.proof.source}) · "
                         f"objection: {brief_of.objection} · action: {brief_of.action}")
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
        caption = item_caption(brief, item)
        if caption is not None:
            lines.append(f"  Caption: {caption.hook}")
        slot: ImageSlot | None = getattr(brief, item.part)
        if slot is not None and slot.ad_fields is not None:
            lines.append(f"  Ad text: {slot.ad_fields.primary_text}")
        if plan is not None:
            others = [o for o in plan.headline_options if not _same(o.text, item.headline)]
            if others:
                lines.append("  Other headlines: " + " | ".join(
                    f'"{o.text}" ({o.score}/6)' for o in others))
            lines.append(f"  Visual: {plan.visual.scene}"
                         + (f" · callouts: {' · '.join(plan.visual.callouts)}"
                            if plan.visual.callouts else ""))
        lines += [f"  ! {problem.removeprefix('[copy] ')}" for problem in found]
        lines += [f"  ~ {warning.removeprefix('[copy] ')}" for warning in warnings]
    if len(items) > 1:  # one topic, several platforms in one package
        pieces = [(f"{item.part} ({item.category})", item.headline, caption_text(brief, item))
                  for item in items]
        lines += [f"  ~ {line.removeprefix('[copy] ')}"
                  for line in near_duplicates("[copy] package", pieces, rules)]
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
    lines, problems = review_lines(folder, brief, load_directions(), services, retry=retry,
                                   settings=settings,
                                   evidence=evidence_text(brief, folder, settings, services))
    if not lines:
        return ["No graphic with a design direction in brief.json: nothing to review."], []
    if approve_it:
        digest = approve(folder, brief, problems)
        lines.append(f"Copy approved ({digest}): its images may be made after the dry run and "
                     "the user's ok. A change to the copy needs a new review.")
        if brief.title_en:  # PRD v6 weekly §6: the folder follows the English title
            from content_automation.content.folder_rename import rename_on_copy

            moved = rename_on_copy(folder, brief.title_en.strip(), settings)
            if moved != folder:
                lines.append(f"Folder named after the English title: {moved}")
                folder = moved
        for item_id in runtime.package_items(folder).values():
            runtime.log(item_id, "decision", {"gate": "copy", "decision": "approved",
                                              "digest": digest})
    return lines, problems


def week_review(settings: Settings, label: str, *, approve_rows: str | None = None,
                retry: bool = False) -> tuple[list[str], list[str]]:
    """The copy review of a calendar week: every Approved row with a package and brief.json.
    approve_rows: "all" or row numbers / BG IDs ("1,3" or "BG-125 BG-126"); a row whose copy
    fails the check is never approved. Returns the lines and the rows not passed or approved."""
    from content_automation.content.brief import BriefError, parse_brief
    from content_automation.content.calendar import APPROVED_STATES, calendar_path, read_view
    from content_automation.content.directions import load_directions
    from content_automation.content.package import BRIEF_FILE, resolve_package_folder

    wanted = {part.strip().upper() for part in re.split(r"[,\s]+", approve_rows or "")
              if part.strip()}
    lines: list[str] = []
    open_rows: list[str] = []
    reviewed: list[tuple[dict[str, str], ContentBrief]] = []
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
        try:
            folder = resolve_package_folder(Path(row["Package"]))
            reviewed.append((row, parse_brief(folder / BRIEF_FILE)))
        except (BriefError, OSError):
            pass
    if reviewed:
        lines += [f"~ {line}" for line in week_warnings(reviewed, load_directions())]
    if not lines:
        lines.append(f"{label}: no Approved row with a package yet (run generate approved "
                     "first: stage 1 and brief.json).")
    return lines, open_rows


def week_warnings(rows: list[tuple[dict[str, str], ContentBrief]],
                  catalog: DirectionCatalog) -> list[str]:
    """P1-R3/R4 across the week (never blocking): a headline pattern chosen by more than
    week.maxSamePattern rows, and near-identical copy of one topic (rows with the same research
    source) on different platforms."""
    rules = load_rules()
    by_pattern: dict[str, list[str]] = {}
    by_source: dict[str, list[tuple[str, str, str]]] = {}
    for row, brief in rows:
        label = f"{row['BG ID'] or 'row ' + row['Row']} ({row['Content type']})"
        for item in copy_items(brief, catalog):
            pattern = chosen_pattern(item)
            if pattern:
                by_pattern.setdefault(pattern, []).append(label)
            source = (row.get("Research source") or "").strip()
            if source:
                by_source.setdefault(source, []).append(
                    (label, item.headline, caption_text(brief, item)))
    limit = int(rules["week"]["maxSamePattern"])
    found = [f"week: the headline pattern {pattern} is used {len(labels)} times "
             f"({', '.join(labels)}); at most {limit} a week: vary the hooks"
             for pattern, labels in sorted(by_pattern.items()) if len(labels) > limit]
    for source, pieces in sorted(by_source.items()):
        if len(pieces) > 1:
            found += near_duplicates(f"week, same topic ({source})", pieces, rules)
    return found


__all__ = ["CopyError", "CopyItem", "Page", "REVIEW_FILE", "RULES_FILE", "approval_problem",
           "approve", "caption_text", "chosen_pattern", "claim_problems", "copy_digest",
           "copy_items", "copy_problems", "evidence_text", "help_block", "is_approved",
           "item_caption", "item_problems", "item_texts", "load_examples", "load_rules",
           "near_duplicates", "package_review", "plan_template", "proof_sources",
           "review_checks", "review_lines", "review_total", "service_id", "style_warnings",
           "week_review", "week_warnings"]
