"""Three script styles, teleprompter and bilingual files, and the storyboard (PRD v5 R9.6-R9.10).

- `brief_text`: the agent's brief per style (internal, English): the 8-step formula with its word
  ranges (config/formulas.json youtube_longform), the style's approach, the verified facts with
  their [S#], and the rules (German only, "Sie", no citations or headings in the teleprompter,
  never an experience Roman did not have, style C scenarios framed as illustrative).
- `teleprompter_problems`: script_de_teleprompter.txt is spoken German only: no English (the German
  pass), no citations, URLs, notes or headings; no first-person experience; style C needs an
  illustrative marker ("Stellen Sie sich vor …"). Length outside 1,300-1,600 words is a warning
  (Q4 open).
- `bilingual_text`: script_de_en_bilingual.txt made FROM the teleprompter file: every German
  paragraph,
  word for word, under "German:", its English under "English:" (kept from the previous file when
  the German paragraph is unchanged, else a placeholder for the agent). `bilingual_problems`
  checks the German is identical paragraph for paragraph and every English block is filled.
- `similarity_flags`: the free difference check between styles (shared word trigrams in the
  openings and in the whole texts).
- `storyboard_text`: one Markdown block per scene for the editing agency (R9.10). PENDING: the
  end of the storyboard spec ("Clear placeholders s…") and its final format are not known yet;
  see STORYBOARD_PENDING. Until they arrive the storyboard is Markdown, one block per scene.

Phase 2 of GERMAN_CONTENT_AND_IMAGE_WORKFLOW_PRD.md (2026-10-22): the briefs carry the argument
outline (research.txt section 12) and the style's angle, opening and order; the teleprompter
check warns about spoken German (long sentences, symbols, brackets and slashes, abbreviations,
digits not written for speaking; config/youtube.json spoken); `trace` maps every factual sentence
to its fact IDs ([F#]); the difference check also flags the same opening type, the same order of
points or facts and near-identical sentences; the bilingual check counts the blocks and warns
when an English block looks summarised; the storyboard names each scene's script paragraphs and
fact IDs and asks for a b-roll or screen-capture suggestion; `storyboard_warnings` flags two
Roman-on-camera scenes in a row, factual scenes without a fact ID and placeholders left.

PRD v6 weekly (2026-10-22): two formats. Long-form (Roman only, about 1,700 words, 3 styles) and
short-form (HOST: and ROMAN: dialogue, about 150 words, one style); each has its own prompt file,
word target and presenter (config/youtube.json formats). Files: teleprompter-de.txt,
script-en-de.md, storyboard.md. No separate sources file: every storyboard scene with a fact is
followed directly by its reference lines (article title, outlet, date, URL) from research.txt
section 5; `reference_problems` makes sure each inline URL is a source the source check opened.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from content_automation.content.german import check_text, load_rules
from content_automation.youtube.research import Research
from content_automation.youtube.sources import normalize
from content_automation.youtube.topic import LONG, SHORT, Style, format_config, load_config

TELEPROMPTER = "teleprompter-de.txt"  # PRD v6 weekly §3 file names
BILINGUAL = "script-en-de.md"
STORYBOARD = "storyboard.md"
LEGACY_NAMES = {"script_de_teleprompter": TELEPROMPTER, "script_de_en_bilingual": BILINGUAL,
                "storyboard": STORYBOARD}  # v6 R7 names -> today's (`ca outputs rename`)
REFERENCE = "**Reference:**"
BRIEF = "brief.md"
ENGLISH_PLACEHOLDER = "<English translation of the German paragraph above>"
# TODO(PENDING, PRD R9.10): the brief was cut off at "Clear placeholders s…". The remaining
# storyboard requirements and the file format (Q6) are unknown: do not guess them. Update
# storyboard_text and docs/v5-implementation-notes.md when they arrive.
STORYBOARD_PENDING = ("PENDING (PRD R9.10): the rest of the storyboard spec and its final "
                      "format are not known yet; this Markdown layout is the interim default.")
_CITATION = re.compile(r"\[[FS]?\d+\]|\([FS]\d+\)|https?://|www\.|\bQuelle\s*:|\bSource\s*:",
                       re.I)
_LABEL = re.compile(r"^(#+\s|\*\*|hook\b|warnung\b|szene\b|scene\b|abschnitt\b|teil \d|"
                    r"schritt \d+\s*:|regie|notiz|note\b|\[|\()", re.I)
_TRIGRAM = re.compile(r"[a-zäöüß]+")
# a sentence ends at . ! ?, but "am 29. Juni" is one sentence (a date's dot before a month)
_SENTENCE = re.compile(r"(?<=[.!?])(?<!\d\.)\s+|(?<=\d\.)\s+(?!(?:Januar|Februar|März|April|Mai"
                       r"|Juni|Juli|August|September|Oktober|November|Dezember)\b)")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_KEY = re.compile(r"[a-zäöüß]{5,}")
_STOP = frozenset({"einer", "eines", "einem", "einen", "diese", "dieser", "dieses", "werden",
                   "wurde", "wurden", "haben", "hatte", "nicht", "durch", "unter", "sowie",
                   "zwischen", "sollte", "sollten", "können", "konnte", "immer", "schon",
                   "genau", "heute", "diesem", "diesen", "damit", "dabei", "einfach", "wirklich"})
_SYMBOL = re.compile(r"[%€$§&+=*#~<>|/]")
_BRACKET = re.compile(r"[()\[\]{}]")
# digits that are not written for speaking: a numeric date, an ISO date, a range with a dash,
# a digit glued to letters ("5G", "3x")
_UNSPOKEN = re.compile(r"\b\d{1,2}\.\d{1,2}\.(?:\d{2,4})?(?!\d)|\b\d{4}-\d{2}-\d{2}\b"
                       r"|\b\d+\s*[-–]\s*\d+\b|\b\d+[A-Za-zÄÖÜäöüß]+\b")
_ON_CAMERA = re.compile(r"\broman\b[^.\n]*\b(?:on camera|camera|kamera)\b", re.I)
_SPEAKER = re.compile(r"^(HOST|ROMAN):\s*")
_REFERENCE_URL = re.compile(r"https?://[^\s)>]+")
_CUTAWAY = re.compile(r"b-roll|cutaway|screen|graphic|grafik|insert|footage|screenshot|"
                      r"animation|map|chart|document", re.I)


def paragraphs(text: str) -> list[str]:
    return [re.sub(r"\s*\n\s*", "\n", block.strip())
            for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]


def words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def speakers(text: str) -> list[str]:
    """The speaker label of each paragraph (short-form), "" where there is none."""
    return [match.group(1) if (match := _SPEAKER.match(block)) else ""
            for block in paragraphs(text)]


def spoken_text(text: str) -> str:
    """The text without the HOST:/ROMAN: labels (what is counted and checked as German)."""
    return "\n\n".join(_SPEAKER.sub("", block) for block in paragraphs(text))


def _prompt(fmt: str) -> str:
    """The format's own writing prompt (config/youtube.json formats.<fmt>.prompt)."""
    path = Path(str(format_config(fmt).get("prompt", "")))
    found = path if path.is_file() else Path(__file__).resolve().parents[3] / path
    return found.read_text(encoding="utf-8").strip() if found.is_file() else ""


def _formula() -> list[dict[str, Any]]:
    path = Path("config/formulas.json")
    found = path if path.is_file() else Path(__file__).resolve().parents[3] / path
    data = json.loads(found.read_text(encoding="utf-8"))
    sections: list[dict[str, Any]] = data["formulas"]["youtube_longform"]["sections"]
    return sections


def brief_text(style: Style, title: str, research: Research, fmt: str = LONG) -> str:
    config = load_config()
    spec = format_config(fmt)
    low, high = spec["targetWords"]
    facts = ([f"- [{fact.id}] {fact.text} ({', '.join(fact.refs)})"
              for fact in research.fact_ids.values()]
             or [f"- {fact} [{', '.join(refs)}]" for fact, refs in research.verified]
             or ["- (no verified facts: run ca youtube check-sources first)"])
    outline = research.outline
    plan = outline.styles.get(style.key)
    points = [f"{n}. {text} [{', '.join(ids)}]" for n, (text, ids) in
              enumerate(outline.points, start=1)]
    own = ([f"- Angle: {plan.angle}", f"- Opening type: {plan.opening} "
            f"({config.get('openingTypes', {}).get(plan.opening, '')})",
            f"- Order of the points: {', '.join(map(str, plan.order)) or 'as in the outline'}"]
           if plan is not None else ["- (no plan for this style in research.txt section 12)"])
    steps = ([f"{n}. {step['key']}: {step['what']} ({step['words'][0]}-{step['words'][1]} "
              "words)" for n, step in enumerate(_formula(), start=1)] if fmt == LONG else [])
    presenter = spec.get("presenter", {})
    per_topic = spec.get("minutesPerTopic")
    return "\n".join([
        f"# Brief: {spec.get('label', fmt)} · style {style.key} {style.name} — {title}",
        "",
        "Internal brief for the writer (English). The teleprompter file is German only.",
        "",
        f"## Format ({spec.get('label', fmt)}, about {spec.get('minutes')} min, {low}-{high} "
        "spoken German words)",
        f"Presenter: {presenter.get('rule', '')}", f"Structure: {spec.get('structure', '')}",
        *([f"Topics in the video: {spec['topicsPerVideo'][0]}-{spec['topicsPerVideo'][1]}, "
           f"{per_topic[0]}-{per_topic[1]} min each by importance (the total stays at the "
           "target)"] if per_topic else []), "",
        f"## Prompt ({spec.get('prompt', '')})", _prompt(fmt) or "-", "",
        f"## Approach ({style.name})", style.approach, "",
        "## Argument outline (research.txt section 12: the same thesis and facts for all styles)",
        f"Thesis: {outline.thesis or '-'}", *points,
        f"Meaning for Germany: {outline.meaning or '-'}", f"Takeaway: {outline.takeaway or '-'}",
        "", *(["## This style's plan (differs from the other two styles)", *own, ""]
              if fmt == LONG else []),
        *(["## Formula (PRD R9.6, adapt the weight per topic)", *steps, ""] if steps else []),
        "## Verified facts (use only these; numbers exactly as written; the IDs stay out of the "
        "teleprompter file)", *facts, "",
        "## Rules",
        f"- Write {TELEPROMPTER} in the {'topic' if fmt == SHORT else 'style'} folder: natural "
        "spoken German for a CEO, address the "
        f"viewer with \"{config.get('address', 'Sie')}\", {low}-{high} words (about "
        f"{low // config['wordsPerMinute']}-{high // config['wordsPerMinute']} minutes), clean "
        "paragraphs separated by one empty line, readable line breaks.",
        "- Nothing that must not be read aloud: no headings, labels, step names, notes, stage "
        "directions, citations, [S#], [F#], URLs or English.",
        "- Spoken German: .agents/skills/german-editorial/references/german-style.md "
        "(\"Gesprochenes Deutsch\"): short sentences, the verb early, no symbols, brackets, "
        "slashes or abbreviations, numbers as spoken.",
        "- Never imply that Roman experienced or witnessed something he did not; no invented "
        "story, number, quotation or event.",
        *(["- Style C: the scenario is illustrative and says so (\"Stellen Sie sich vor …\").",
           "- The three styles differ in hook, story, delivery and structure, not only in "
           "wording."] if fmt == LONG else
          ["- Every paragraph starts with HOST: or ROMAN: (the only labels allowed; they mark "
           "Roman's lines on the teleprompter). Both speak; the first line is the hook."]),
        f"- Then run: uv run ca youtube bilingual <BG-ID> (it makes {BILINGUAL} from your "
        "German; fill every English block).",
    ]) + "\n"


def teleprompter_problems(text: str, style_key: str,
                          fmt: str = LONG) -> tuple[list[str], list[str]]:
    """(errors, warnings) of one teleprompter file. Short-form: every paragraph starts with
    HOST: or ROMAN: and both speak; long-form: Roman only, no speaker labels."""
    config = load_config()
    spec = format_config(fmt)
    errors: list[str] = []
    warnings: list[str] = []
    if not paragraphs(text):
        return ["the file is empty"], []
    labels = speakers(text)
    if fmt == SHORT:
        unlabelled = [str(n) for n, label in enumerate(labels, start=1) if not label]
        if unlabelled:
            errors.append(f"paragraph(s) {', '.join(unlabelled)}: start with HOST: or ROMAN: "
                          "(short-form dialogue)")
        missing = sorted({"HOST", "ROMAN"} - set(labels))
        if missing:
            errors.append(f"short-form dialogue: {' and '.join(missing)} never speaks")
    elif "HOST" in labels:
        errors.append("long-form is Roman only: no HOST: lines")
    text = spoken_text(text)
    blocks = paragraphs(text)
    for number, block in enumerate(blocks, start=1):
        first = block.splitlines()[0].strip()
        if _CITATION.search(block):
            errors.append(f"paragraph {number}: a citation, URL or source note (not spoken)")
        if _LABEL.match(first) or (len(first.split()) <= 6 and first.endswith(":")) or (
                first.isupper() and len(first.split()) <= 8):
            errors.append(f'paragraph {number}: "{first[:40]}" reads as a heading or label')
    german = check_text(text, "teleprompter", load_rules())
    errors += german.errors
    warnings += german.warnings
    lowered = text.lower()
    for phrase in config.get("firstPersonExperience", []):
        if phrase in lowered:
            errors.append(f'"{phrase}": never imply Roman experienced something he did not '
                          "(R9.7)")
    if style_key.upper() == "C" and not any(marker in lowered
                                           for marker in config.get("illustrativeMarkers", [])):
        errors.append('style C: frame the scenario as illustrative ("Stellen Sie sich vor …")')
    low, high = spec["targetWords"]
    count = words(text)
    if not low <= count <= high:
        warnings.append(f"{count} words; the {spec.get('label', fmt)} target is {low}-{high} "
                        f"(about {spec.get('minutes')} min)")
    return errors, warnings + spoken_warnings(text)


def sentences(text: str) -> list[tuple[int, str]]:
    """(paragraph number, sentence) of a teleprompter text."""
    return [(number, part.strip()) for number, block in enumerate(paragraphs(text), start=1)
            for part in _SENTENCE.split(block.replace("\n", " ")) if part.strip()]


def spoken_warnings(text: str) -> list[str]:
    """P2-R5 (never blocking): what is hard to read aloud, one warning per kind."""
    rules = load_config().get("spoken", {})
    limit = int(rules.get("sentenceMaxWords", 15))
    found: dict[str, list[str]] = {}
    for number, sentence in sentences(text):
        at = f"¶{number}"
        if words(sentence) > limit:
            found.setdefault(f"sentences over {limit} words (split them; verb early)", []).append(
                f"{at} {words(sentence)}")
        if hit := _SYMBOL.search(sentence):
            found.setdefault("symbols or slashes (write them as spoken)", []).append(
                f'{at} "{hit.group(0)}"')
        if _BRACKET.search(sentence):
            found.setdefault("brackets (say it as its own sentence)", []).append(at)
        for short in rules.get("abbreviations", []):
            if re.search(rf"(?<![\wäöüß]){re.escape(short)}", sentence):
                found.setdefault("abbreviations (write them out)", []).append(
                    f'{at} "{short}"')
        if hit := _UNSPOKEN.search(sentence):
            found.setdefault("digits not written for speaking (a date or range in words)",
                             []).append(f'{at} "{hit.group(0)}"')
    return [f"spoken German: {len(hits)} {kind}: {', '.join(hits[:6])}"
            + (" …" if len(hits) > 6 else "") for kind, hits in found.items()]


def _stems(text: str) -> set[str]:
    return {word[:6] for word in _KEY.findall(normalize(text)) if word not in _STOP}


def fact_ids_for(text: str, research: Research) -> list[str]:
    """The fact IDs a sentence states: its numbers are in the fact and its key words match."""
    plain = normalize(text)
    numbers = set(_NUMBER.findall(plain))
    stems = _stems(text)
    scored: list[tuple[int, str]] = []
    for fact in research.fact_ids.values():
        body = normalize(f"{fact.text} {fact.support}")
        if numbers and not numbers <= set(_NUMBER.findall(body)):
            continue
        hits = sum(1 for stem in stems if stem in body)
        if (numbers and hits >= 1) or (hits >= 2 and hits >= 0.3 * len(stems)):
            scored.append((hits, fact.id))
    best = max((hits for hits, _ in scored), default=0)
    return sorted({fact for hits, fact in scored if hits == best},
                  key=lambda fact: int(fact[1:]))


def factual(sentence: str) -> bool:
    """A sentence that states a fact: a digit, a number word (copy_rules claims numberWords)
    or an attribution word (config/youtube.json spoken.attributionWords)."""
    from content_automation.content.copy_check import load_rules as copy_rules

    claims = copy_rules()["claims"]
    counted = "|".join(re.escape(word.lower()) for word in
                       [*claims["scenarioUnits"], *claims["ownCounts"]])
    numbers = "|".join([r"\d+(?:[.,]\d+)*", *map(re.escape, claims["numberWords"])])
    lowered = sentence.lower()
    # a number that is not a count of the script's own points ("drei Fragen"), a timing or part
    # of a compound ("Vier-Augen-Prinzip")
    for match in re.finditer(rf"(?<![\wäöüß-])({numbers})(?![\wäöüß-])", lowered):
        if not re.match(rf"\s*(?:{counted})\b", lowered[match.end():]):
            return True
    attribution = [word.lower() for word in load_config().get("spoken", {}).get(
        "attributionWords", [])]
    return any(re.search(rf"(?<![\wäöüß]){re.escape(word)}(?![\wäöüß])", lowered)
               for word in attribution)


def trace(text: str, research: Research) -> list[tuple[int, str, list[str]]]:
    """P2-R2: (paragraph, sentence, fact IDs) of every factual sentence of a script; an empty
    list means the sentence is not traceable to research.txt."""
    return [(number, sentence, fact_ids_for(sentence, research))
            for number, sentence in sentences(text) if factual(sentence)]


def trace_warnings(text: str, research: Research) -> tuple[str, list[str]]:
    """(the summary line, a warning per factual sentence without a fact ID)."""
    rows = trace(text, research)
    missing = [(number, sentence) for number, sentence, ids in rows if not ids]
    summary = (f"traceability: {len(rows) - len(missing)} of {len(rows)} factual sentence(s) "
               "map to fact IDs")
    return summary, [f'¶{number} "{sentence[:90]}": no fact ID in research.txt (use a fact of '
                     "section 7/11a, or leave it out)" for number, sentence in missing]


def bilingual_text(teleprompter: str, previous: str | None = None) -> str:
    """script_de_en_bilingual.txt from the teleprompter: German word for word, English under
    each."""
    kept = dict(read_bilingual(previous)) if previous else {}
    out: list[str] = []
    for block in paragraphs(teleprompter):
        english = kept.get(block, "")
        out += ["German:", block, "", "English:",
                english if english and english != ENGLISH_PLACEHOLDER else ENGLISH_PLACEHOLDER,
                ""]
    return "\n".join(out).rstrip() + "\n"


def read_bilingual(text: str | None) -> list[tuple[str, str]]:
    """(German, English) pairs of a bilingual file."""
    if not text:
        return []
    pairs: list[tuple[str, str]] = []
    for chunk in re.split(r"(?m)^German:\s*$", text)[1:]:
        german, _, english = chunk.partition("\nEnglish:")
        pairs.append((paragraphs(german)[0] if paragraphs(german) else "",
                      english.strip()))
    return pairs


def bilingual_problems(teleprompter: str, bilingual: str) -> list[str]:
    """R9.9: the German in the bilingual file is the teleprompter's, paragraph for paragraph;
    every English block is written (and is English)."""
    source = paragraphs(teleprompter)
    pairs = read_bilingual(bilingual)
    problems: list[str] = []
    if len(pairs) != len(source):
        problems.append(f"{len(pairs)} German blocks, the teleprompter has {len(source)} "
                        "paragraphs: run ca youtube bilingual again")
    heads = (len(re.findall(r"(?m)^German:\s*$", bilingual)),
             len(re.findall(r"(?m)^English:\s*$", bilingual)))
    english_blocks = sum(len(paragraphs(english)) or 1 for _, english in pairs)
    if heads[0] != heads[1] or english_blocks != len(pairs):  # P2-R6: German = English blocks
        problems.append(f"{heads[0]} German block(s), {max(heads[1], english_blocks)} English "
                        "block(s): one English block (one paragraph) under each German block")
    for number, (german, (copied, english)) in enumerate(zip(source, pairs, strict=False),
                                                         start=1):
        if copied != german:
            problems.append(f"paragraph {number}: the German differs from {TELEPROMPTER}")
        if not english or english == ENGLISH_PLACEHOLDER:
            problems.append(f"paragraph {number}: the English translation is missing")
        elif sum(1 for word in ("der", "die", "und", "nicht", "sie", "ist")
                 if re.search(rf"\b{word}\b", english.lower())) >= 3:
            problems.append(f"paragraph {number}: the English block reads as German")
    return problems


def bilingual_warnings(teleprompter: str, bilingual: str) -> list[str]:
    """P2-R6 (never blocking): an English block with clearly fewer sentences or words than its
    German block may be summarised; translate every sentence."""
    warnings: list[str] = []
    for number, (german, english) in enumerate(read_bilingual(bilingual), start=1):
        if not english or english == ENGLISH_PLACEHOLDER:
            continue
        de = [part for part in _SENTENCE.split(german.replace("\n", " ")) if part.strip()]
        en = [part for part in _SENTENCE.split(english.replace("\n", " ")) if part.strip()]
        if len(en) < len(de) or words(english) < 0.7 * words(german):
            warnings.append(f"bilingual ¶{number}: {len(en)} English sentence(s) for {len(de)} "
                            f"German, {words(english)} words for {words(german)}: translate "
                            "every sentence, do not summarise")
    return warnings


def _trigrams(text: str) -> set[tuple[str, str, str]]:
    tokens = _TRIGRAM.findall(text.lower())
    return set(zip(tokens, tokens[1:], tokens[2:], strict=False))


def _overlap(first: str, second: str) -> float:
    one, two = _trigrams(first), _trigrams(second)
    return len(one & two) / max(1, min(len(one), len(two)))


def opening_type(text: str) -> str:
    """How a script opens (the first sentence): question, scenario, quote or statement."""
    first = next((sentence for _, sentence in sentences(text)), "")
    lowered = first.lower()
    if any(marker in lowered for marker in load_config().get("illustrativeMarkers", [])):
        return "scenario"
    if first.rstrip().endswith("?"):
        return "question"
    if first[:1] in "\"„“»":
        return "quote"
    return "statement"


_DETECTED = {"question": "question", "scenario": "scenario", "quote": "quote"}


def _near_pairs(first: list[str], second: list[str], ratio: float) -> list[str]:
    """`first`'s sentences that have a near-identical sentence in `second`."""
    hits: list[str] = []
    for sentence in first:
        for other in second:
            match = SequenceMatcher(None, sentence, other)
            if (match.real_quick_ratio() >= ratio and match.quick_ratio() >= ratio
                    and match.ratio() >= ratio):
                hits.append(sentence)
                break
    return hits


def _fact_order(text: str, research: Research) -> list[str]:
    order: list[str] = []
    for _, _, ids in trace(text, research):
        order += [fact for fact in ids if fact not in order]
    return order


def structure_flags(texts: dict[str, str], research: Research | None) -> list[str]:
    """P2-R4: pairs with the same opening type, the same order of points or facts, or a high
    share of near-identical sentences."""
    config = load_config()["similarity"]
    plans = research.outline.styles if research is not None else {}
    opened = {key: opening_type(text) for key, text in texts.items()}
    flags: list[str] = []
    for key, detected in opened.items():
        declared = plans[key].opening if key in plans else ""
        if declared and _DETECTED.get(declared, "statement") != detected:
            flags.append(f"style {key}: the outline says the opening is a {declared}, the script "
                         f"opens with a {detected}")
    long = {key: [normalize(sentence) for _, sentence in sentences(text)
                  if words(sentence) >= 6] for key, text in texts.items()}
    orders = {key: _fact_order(text, research) for key, text in texts.items()} if (
        research is not None) else {}
    keys = sorted(texts)
    for index, first in enumerate(keys):
        for second in keys[index + 1:]:
            pair = f"styles {first} and {second}"
            one = plans[first].opening if first in plans else ""
            two = plans[second].opening if second in plans else ""
            # two statements differ when the outline gives them different types (incident,
            # statistic, contradiction)
            if opened[first] == opened[second] and (opened[first] != "statement"
                                                     or (one and one == two)):
                flags.append(f"{pair}: the same opening type ({one or opened[first]})")
            if first in plans and second in plans and plans[first].order and (
                    plans[first].order == plans[second].order):
                flags.append(f"{pair}: the same order of the outline points "
                             f"({', '.join(map(str, plans[first].order))})")
            if orders and len(orders[first]) >= int(config.get("minSameFactOrder", 3)) and (
                    orders[first] == orders[second]):
                flags.append(f"{pair}: the facts come in the same order "
                             f"({', '.join(orders[first])})")
            ratio = float(config["sentenceRatio"])
            near = max((_near_pairs(long[first], long[second], ratio), long[first]),
                       (_near_pairs(long[second], long[first], ratio), long[second]),
                       key=lambda found: len(found[0]) / max(1, len(found[1])))
            share = len(near[0]) / max(1, len(near[1]))
            if share > float(config["maxSentenceOverlap"]):
                flags.append(f"{pair}: {share:.0%} near-identical sentences (at most "
                             f"{float(config['maxSentenceOverlap']):.0%}), e.g. "
                             f'"{near[0][0][:70]}"')
    return flags


def similarity_flags(texts: dict[str, str], research: Research | None = None) -> list[str]:
    """Style pairs whose openings or whole texts are too similar (R9.7); with the research file
    also the opening types, the order and near-identical sentences (P2-R4)."""
    config = load_config()["similarity"]
    opening = int(config["openingWords"])
    flags: list[str] = []
    keys = sorted(texts)
    for index, first in enumerate(keys):
        for second in keys[index + 1:]:
            head = _overlap(" ".join(texts[first].split()[:opening]),
                            " ".join(texts[second].split()[:opening]))
            whole = _overlap(texts[first], texts[second])
            if head > float(config["maxOpeningOverlap"]):
                flags.append(f"styles {first} and {second}: the openings are too similar "
                             f"({head:.0%} shared word trigrams)")
            if whole > float(config["maxTextOverlap"]):
                flags.append(f"styles {first} and {second}: the texts are too similar "
                             f"({whole:.0%} shared word trigrams)")
    return flags + structure_flags(texts, research)


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def reference_lines(ids: list[str], research: Research) -> list[str]:
    """One inline reference line per source of these fact IDs: title, outlet, date, URL."""
    refs = sorted({ref for fact in ids for ref in research.fact_ids[fact].refs},
                  key=lambda ref: int(ref[1:]) if ref[1:].isdigit() else 0)
    found = [research.sources[ref] for ref in refs if ref in research.sources]
    return [f"{REFERENCE} {source.title}, {source.publisher}, {source.date}, {source.url}"
            for source in found]


def storyboard_text(style: Style, title: str, bg_id: str, teleprompter: str, bilingual: str,
                    research: Research, fmt: str = LONG) -> str:
    """One Markdown block per scene (paragraphs merged up to the scene length); the references
    follow the scene's spoken text directly (no separate sources file)."""
    config = load_config()
    spec = format_config(fmt)
    voice = "HOST and ROMAN" if fmt == SHORT else "Roman"
    per_second = float(config["wordsPerMinute"]) / 60
    shortest = float(config["storyboardSecondsPerScene"][0])
    english = dict(read_bilingual(bilingual))
    scenes: list[list[tuple[int, str]]] = []
    for number, block in enumerate(paragraphs(teleprompter), start=1):
        if scenes and words(" ".join(text for _, text in scenes[-1])) / per_second < shortest:
            scenes[-1].append((number, block))
        else:
            scenes.append([(number, block)])
    lines = [f"# Storyboard: {title}", "",
             f"{bg_id} · {spec.get('label', fmt)} · style {style.key} {style.name} · for the "
             f"editing agency (English explanations; {voice} record the German lines)", "",
             f"Style: {style.approach}", "",
             f"> {STORYBOARD_PENDING}", "",
             "Fill every <…> before handing it over. Every scene that states a fact, figure or "
             f"news item is followed directly by its {REFERENCE} line(s): article title, outlet, "
             "date, URL. Never show an unverifiable event as real: illustrative footage is "
             "labelled as such. Never two Roman-on-camera scenes in a row without a cutaway "
             "(b-roll, screen capture, graphic).", ""]
    start = 0.0
    for number, blocks in enumerate(scenes, start=1):
        spoken = "\n\n".join(text for _, text in blocks)
        seconds = words(spoken) / per_second
        ids = sorted({fact for _, _, found in trace(spoken, research) for fact in found},
                     key=lambda fact: int(fact[1:]))
        references = reference_lines(ids, research) or (
            [f"{REFERENCE} <article title, outlet, YYYY-MM-DD, URL from research.txt section 5, "
             "or none>"] if any(ch.isdigit() for ch in spoken) else [])
        translated = "\n\n".join(english.get(text, ENGLISH_PLACEHOLDER) for _, text in blocks)
        numbers = [block for block, _ in blocks]
        span = f"{numbers[0]}" if len(numbers) == 1 else f"{numbers[0]}–{numbers[-1]}"
        lines += [
            f"## Scene {number} · {_clock(start)}–{_clock(start + seconds)} (≈ {seconds:.0f} s)",
            "", f"**Script paragraphs:** {span}", "",
            f"**German (spoken by {voice}):**", "", spoken, "",
            *(line for reference in references for line in (reference, "")),
            "**English (translation):**", "", translated, "",
            "**Visual direction:** <what the viewer sees: Roman on camera, or a cutaway (b-roll, "
            "screen capture, graphic); never two Roman-on-camera scenes in a row>", "",
            "**B-roll / screen capture (English, for the editor):** <a concrete suggestion, "
            "labelled illustrative when it does not show the real event>", "",
            "**Graphics, diagrams, animations, screenshots, illustrations:** <what to build>",
            "",
            "**On-screen text (German, exact):** <the exact German text, or none>", "",
            "**On-screen text (English explanation):** <what it says, for the editor>", "",
            f"**Fact IDs:** {', '.join(ids) or 'none'}", "",
            "**Transitions, pacing, supporting footage:** <cut, tempo, music, footage>", "",
            "**Placeholders:** TODO (PENDING spec, PRD R9.10)", "",
        ]
        start += seconds
    return "\n".join(lines).rstrip() + "\n"


def reference_problems(text: str, research: Research | None) -> list[str]:
    """PRD v6 weekly §5: every inline reference URL of a storyboard is a research.txt source,
    so the source check (dead URL, misquote) has opened it."""
    if research is None:
        return []
    known = {source.url.rstrip("/") for source in research.sources.values()}
    problems: list[str] = []
    for line in text.splitlines():
        if line.startswith(REFERENCE):
            for url in _REFERENCE_URL.findall(line):
                if url.rstrip("/.,") not in known and url.rstrip("/") not in known:
                    problems.append(f"storyboard reference {url}: not a source in research.txt "
                                    "section 5, so the source check never opened it")
    return problems


def storyboard_warnings(text: str) -> list[str]:
    """P2-R7 (never blocking): placeholders left, two Roman-on-camera scenes in a row without a
    cutaway, and a scene with a number in its German line but no fact ID."""
    warnings: list[str] = []
    scenes = re.split(r"(?m)^## Scene ", text)[1:]
    on_camera: list[bool] = []
    open_scenes = [str(number) for number, scene in enumerate(scenes, start=1)
                   if re.search(r"<[^>\n]{3,}>", scene)]
    if open_scenes:
        warnings.append(f"storyboard: <…> placeholders left in scene(s) {', '.join(open_scenes)}")
    for number, scene in enumerate(scenes, start=1):
        visual = re.search(r"\*\*Visual direction:\*\*\s*(.*)", scene)
        seen = visual.group(1) if visual else ""
        roll = re.search(r"\*\*B-roll / screen capture[^*]*\*\*\s*(.*)", scene)
        cut = bool(_CUTAWAY.search(seen)) or bool(roll and roll.group(1).strip()
                                                    and "<" not in roll.group(1))
        on_camera.append(bool(_ON_CAMERA.search(seen)) and not cut)
        german = re.split(r"\*\*German \(spoken by [^)]*\):\*\*", scene, maxsplit=1)[-1]
        german = german.split(REFERENCE, 1)[0].split("**English", 1)[0]
        if re.search(r"\d", german) and not _REFERENCE_URL.search(
                scene.split("**English", 1)[0]):
            warnings.append(f"storyboard scene {number}: a number in the German line but no "
                            f"{REFERENCE} line with a URL right after it")
    for number in range(1, len(on_camera)):
        if on_camera[number - 1] and on_camera[number]:
            warnings.append(f"storyboard scenes {number} and {number + 1}: Roman on camera twice "
                            "in a row; add a cutaway (b-roll, screen capture, graphic)")
    return warnings


__all__ = ["BILINGUAL", "BRIEF", "ENGLISH_PLACEHOLDER", "LEGACY_NAMES", "REFERENCE", "STORYBOARD",
           "STORYBOARD_PENDING", "TELEPROMPTER", "reference_lines", "reference_problems",
           "speakers", "spoken_text",
           "bilingual_problems", "bilingual_text", "bilingual_warnings", "brief_text",
           "fact_ids_for", "factual", "opening_type", "paragraphs", "read_bilingual",
           "sentences", "similarity_flags", "spoken_warnings", "storyboard_text",
           "storyboard_warnings", "structure_flags", "teleprompter_problems", "trace",
           "trace_warnings", "words"]
