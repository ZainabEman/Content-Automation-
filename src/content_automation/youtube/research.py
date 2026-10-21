"""The research TXT of a topic (PRD v5 R9.4): template, parser and the free structure check.

Plain UTF-8. Sections start with "== <number>. <TITLE> ==". Sources are numbered [S1], [S2] …:
section 5 lists "[S1] Title | Publisher | YYYY-MM-DD", section 6 "[S1] https://…". Facts
(sections 7 and 11a) are lines "- <fact> [S1]"; quotations (section 8) are lines
"- \"<quote>\" — <name, role> [S2]". The VERIFICATION section is written by
`ca youtube check-sources` and replaced on every run. Nothing here is invented: the agent fills
the template from sources it opened; the check refuses placeholders and facts without a source.

Phase 2 of GERMAN_CONTENT_AND_IMAGE_WORKFLOW_PRD.md (2026-10-22): every fact of sections 7 and 11a
carries a fact ID, "- [F1] <fact> [S1] | Beleg: \"<supporting quote>\"" (the Beleg is optional:
quoted, the source check looks for it word for word; unquoted, it is a paraphrase). The same fact
keeps its ID in both sections; the source's publisher, title, date and URL come from [S1].
Section 12 is the argument outline the three scripts are drafted from: the thesis, 3-4 points
with their fact IDs, the meaning for Germany, the takeaway and per style its angle, its opening
type (config/youtube.json openingTypes) and the order of the points.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SECTIONS: list[tuple[str, str]] = [
    ("1", "TOPIC AND WORKING TITLE"),
    ("2", "WHY IT MATTERS TO GERMAN VIEWERS"),
    ("3", "SUMMARY OF THE INCIDENT, PROBLEM OR FINDING"),
    ("4", "PUBLICATION AND EVENT DATES"),
    ("5", "ARTICLE TITLES AND PUBLISHERS"),
    ("6", "SOURCE URLS"),
    ("7", "KEY STATISTICS AND FACTS (each with its source)"),
    ("8", "QUOTATIONS (accurately attributed)"),
    ("9", "CLAIMS THAT NEED CAREFUL QUALIFICATION"),
    ("10", "CONFLICTING INFORMATION AND SOURCE LIMITATIONS"),
    ("11a", "VERIFIED FACTS"),
    ("11b", "INTERPRETATION"),
    ("11c", "PROPOSED SOLUTIONS"),
    ("12", "ARGUMENT OUTLINE (before drafting the scripts)"),
]
VERIFICATION = "VERIFICATION (written by ca youtube check-sources)"
_HEADING = re.compile(r"^==\s*(?:(\w+)\.\s*)?(.+?)\s*==\s*$", re.M)
_REF = re.compile(r"\[S(\d+)\]")
_FACT_ID = re.compile(r"\[F(\d+)\]")
_SUPPORT = re.compile(r"\s*\|\s*Beleg:\s*", re.I)
_IDS = re.compile(r"\bF(\d+)\b")
_OUTLINE_LINE = re.compile(r"^\s*(Thesis|Point\s*(\d+)|Meaning|Takeaway|Style\s+(\w))\s*:\s*(.*)$",
                           re.I)
_SOURCE_LINE = re.compile(r"^\s*\[S(\d+)\]\s*(.+?)\s*$")
_QUOTE = re.compile(r"[\"„“”»«]([^\"„“”»«]{8,})[\"„“”»«]")
_PLACEHOLDER = re.compile(r"<[^>]{3,}>")


@dataclass
class Source:
    id: str
    title: str = ""
    publisher: str = ""
    date: str = ""
    url: str = ""


@dataclass
class Fact:
    """A fact with its ID (P2-R2): the text, its sources and the supporting quote or paraphrase."""

    id: str
    text: str
    refs: list[str]
    support: str = ""
    quoted: bool = False  # the support is a quotation the source check looks for word for word


@dataclass
class StylePlan:
    key: str
    angle: str = ""
    opening: str = ""
    order: list[int] = field(default_factory=list)  # the outline points in the script's order


@dataclass
class Outline:
    """Section 12 (P2-R3): what all three scripts argue."""

    thesis: str = ""
    points: list[tuple[str, list[str]]] = field(default_factory=list)  # (point, fact ids)
    meaning: str = ""
    takeaway: str = ""
    styles: dict[str, StylePlan] = field(default_factory=dict)


@dataclass
class Research:
    sections: dict[str, str]
    sources: dict[str, Source] = field(default_factory=dict)
    facts: list[tuple[str, list[str]]] = field(default_factory=list)  # (text, source ids)
    verified: list[tuple[str, list[str]]] = field(default_factory=list)
    quotes: list[tuple[str, list[str]]] = field(default_factory=list)  # (quote, source ids)
    fact_ids: dict[str, Fact] = field(default_factory=dict)  # F1 -> the fact (sections 7, 11a)
    unnumbered: list[str] = field(default_factory=list)  # fact lines without an [F#]
    outline: Outline = field(default_factory=Outline)


def _outline_template() -> str:
    from content_automation.youtube.topic import load_config, styles

    openings = " | ".join(load_config().get("openingTypes", {}))
    lines = ["Thesis: <the one central thesis of all three scripts, one sentence>",
             "Point 1: <a supporting point> [F1]", "Point 2: <a supporting point> [F2]",
             "Point 3: <a supporting point> [F3]",
             "Meaning: <what it means for German businesses or people>",
             "Takeaway: <the practical takeaway>"]
    for key, style in styles().items():
        default = str(load_config()["styles"][key].get("opening", ""))
        lines.append(f"Style {key}: angle: <the editorial angle of {style.name}> | opening: "
                     f"<{default or openings}> | order: <the point numbers in this script's "
                     "order, e.g. 1, 2, 3>")
    lines.append(f"(opening types: {openings}; each style a different opening and order)")
    return "\n".join(lines)


def template(title: str, bg_id: str, month: str, slug_text: str) -> str:
    """The empty research file; every <…> must be replaced from opened sources."""
    body = {
        "1": f"Topic: {title}\nWorking title (DE): <German working title>\n"
             "English gloss: <English gloss of the title>",
        "2": "<why this matters to individuals, businesses or society in Germany>",
        "3": "<what happened or what was found, in plain words, with its sources [S1]>",
        "4": "<the publication dates and event dates, each with [S#]>",
        "5": "[S1] <article title> | <publisher> | <YYYY-MM-DD>\n"
             "[S2] <article title> | <publisher> | <YYYY-MM-DD>",
        "6": "[S1] <https://full URL as opened>\n[S2] <https://full URL as opened>",
        "7": "- [F1] <a statistic or fact, exactly as the source states it> [S1] | Beleg: "
             "\"<the supporting quote from the page, or a close paraphrase without quotes>\"",
        "8": "- \"<an exact quotation from the page>\" — <name, role> [S2]\n"
             "(or: none)",
        "9": "<claims that need careful wording, and why>",
        "10": "<where sources disagree, what is unknown, the limits of each source>",
        "11a": "- [F1] <a fact the sources state directly; the same fact keeps its ID from "
               "section 7> [S1]",
        "11b": "<what it means: clearly marked as interpretation>",
        "11c": "<practical, responsible solutions for German viewers>",
        "12": _outline_template(),
    }
    lines = [f"RESEARCH: {title}", f"BG ID: {bg_id} | Month: {month} | Slug: {slug_text}",
             "Rules: real incidents and documented problems only; never invent a source, URL, "
             "title, quotation, number or event; every fact names its [S#] and has a fact ID "
             "[F#]. Sources: primary and reputable German sources first; newsletters only as "
             "leads (cite the original); social posts only as attributed illustration, never "
             "as sole proof.", ""]
    for key, name in SECTIONS:
        lines += [f"== {key}. {name} ==", body[key], ""]
    lines += [f"== {VERIFICATION} ==", "(not checked yet: uv run ca youtube check-sources "
              f"{bg_id})", ""]
    return "\n".join(lines)


def _split(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    matches = list(_HEADING.finditer(text))
    for index, match in enumerate(matches):
        key = match.group(1) or match.group(2).split(" ")[0]
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        found[key] = text[match.end():end].strip()
    return found


def _items(text: str) -> list[tuple[str, list[str]]]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("-"):
            claim = _SUPPORT.split(line, maxsplit=1)[0]
            rows.append((_FACT_ID.sub("", _REF.sub("", claim.lstrip("- "))).strip(),
                         [f"S{n}" for n in _REF.findall(claim)]))
    return rows


def _facts(text: str, research: Research, where: str) -> None:
    """The fact lines of a section into research.fact_ids (an ID keeps its first text)."""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        claim, *rest = _SUPPORT.split(line, maxsplit=1)
        support = rest[0].strip() if rest else ""
        ids = _FACT_ID.findall(claim)
        fact_text = _FACT_ID.sub("", _REF.sub("", claim.lstrip("- "))).strip()
        if not ids:
            research.unnumbered.append(f'section {where}: "{fact_text[:50]}"')
            continue
        key = f"F{ids[0]}"
        quoted = support[:1] in "\"„“»" and len(support) > 2
        found = research.fact_ids.setdefault(key, Fact(
            key, fact_text, [f"S{n}" for n in _REF.findall(claim)],
            support.strip("\"„“”»« ") if quoted else support, quoted))
        if found.text != fact_text and not found.support and support:
            found.support, found.quoted = support.strip("\"„“”»« "), quoted


def _outline(text: str) -> Outline:
    outline = Outline()
    for line in text.splitlines():
        match = _OUTLINE_LINE.match(line)
        if not match:
            continue
        kind, value = match.group(1).lower(), match.group(4).strip()
        if kind == "thesis":
            outline.thesis = value
        elif kind.startswith("point"):
            outline.points.append((_FACT_ID.sub("", re.sub(r"\[(F\d+(?:\s*,\s*F\d+)*)\]", "",
                                                         value)).strip(),
                                   [f"F{n}" for n in _IDS.findall(
                                       " ".join(re.findall(r"\[([^\]]*)\]", value)))]))
        elif kind == "meaning":
            outline.meaning = value
        elif kind == "takeaway":
            outline.takeaway = value
        else:
            parts = {part.split(":", 1)[0].strip().lower(): part.split(":", 1)[1].strip()
                     for part in value.split("|") if ":" in part}
            key = (match.group(3) or "").upper()
            outline.styles[key] = StylePlan(
                key, parts.get("angle", ""), parts.get("opening", "").lower(),
                [int(n) for n in re.findall(r"\d+", parts.get("order", ""))])
    return outline


def parse(text: str) -> Research:
    sections = _split(text)
    research = Research(sections=sections)
    for line in sections.get("5", "").splitlines():
        match = _SOURCE_LINE.match(line)
        if match:
            parts = [part.strip() for part in match.group(2).split("|")]
            source = research.sources.setdefault(f"S{match.group(1)}",
                                                 Source(f"S{match.group(1)}"))
            source.title = parts[0]
            source.publisher = parts[1] if len(parts) > 1 else ""
            source.date = parts[2] if len(parts) > 2 else ""
    for line in sections.get("6", "").splitlines():
        match = _SOURCE_LINE.match(line)
        if match:
            research.sources.setdefault(f"S{match.group(1)}",
                                        Source(f"S{match.group(1)}")).url = match.group(2)
    research.facts = _items(sections.get("7", ""))
    research.verified = _items(sections.get("11a", ""))
    _facts(sections.get("7", ""), research, "7")
    _facts(sections.get("11a", ""), research, "11a")
    research.outline = _outline(sections.get("12", ""))
    for quote_line, refs in _items(sections.get("8", "")):
        match = _QUOTE.search(quote_line)
        if match:
            research.quotes.append((match.group(1).strip(), refs))
    return research


def read(path: Path) -> Research:
    return parse(path.read_text(encoding="utf-8"))


def structure_problems(research: Research) -> list[str]:
    """Free: every R9.4 section filled, no placeholder, sources complete, facts sourced."""
    problems: list[str] = []
    for key, name in SECTIONS:
        body = research.sections.get(key, "")
        if not body.strip():
            problems.append(f"section {key} ({name}) is missing or empty")
        elif _PLACEHOLDER.search(body):
            problems.append(f"section {key} ({name}) still has a <placeholder>")
    if len(research.sources) < 2:
        problems.append("at least 2 sources ([S1], [S2] in sections 5 and 6)")
    for source in research.sources.values():
        if not source.url.startswith(("http://", "https://")):
            problems.append(f"{source.id}: no full URL in section 6")
        if not source.title or not source.publisher:
            problems.append(f"{source.id}: title and publisher in section 5")
    if not research.verified:
        problems.append("section 11a lists no verified fact")
    problems += [f"{line} has no fact ID [F#] (P2-R2)" for line in research.unnumbered]
    problems += outline_problems(research)
    for where, rows in (("7", research.facts), ("11a", research.verified),
                        ("8", research.quotes)):
        for text, refs in rows:
            if not refs:
                problems.append(f'section {where}: "{text[:50]}" names no source [S#]')
            for ref in refs:
                if ref not in research.sources:
                    problems.append(f'section {where}: "{text[:50]}" cites {ref}, which is '
                                    "not in sections 5 and 6")
    return problems


def outline_problems(research: Research) -> list[str]:
    """P2-R3: the thesis, 3-4 points with known fact IDs, the meaning, the takeaway, and per
    style an angle, an opening type and (if given) an order of the points."""
    from content_automation.youtube.topic import load_config, styles

    outline = research.outline
    openings = set(load_config().get("openingTypes", {}))
    problems: list[str] = []
    if not outline.thesis:
        problems.append("section 12: write the Thesis: line")
    if not 3 <= len(outline.points) <= 4:
        problems.append(f"section 12: {len(outline.points)} point(s); write 3-4 (Point 1: … "
                        "[F1])")
    for number, (_, ids) in enumerate(outline.points, start=1):
        if not ids:
            problems.append(f"section 12: Point {number} names no fact ID [F#]")
        problems += [f"section 12: Point {number} cites {fact}, which is not in sections 7 "
                     "and 11a" for fact in ids if fact not in research.fact_ids]
    if not outline.meaning or not outline.takeaway:
        problems.append("section 12: write the Meaning: and Takeaway: lines")
    for key in styles():
        plan = outline.styles.get(key)
        if plan is None or not plan.angle:
            problems.append(f"section 12: Style {key}: angle: … | opening: … | order: …")
            continue
        if plan.opening not in openings:
            problems.append(f'section 12: Style {key} opening "{plan.opening}": one of '
                            f"{', '.join(sorted(openings))}")
        wrong = [n for n in plan.order if not 1 <= n <= len(outline.points)]
        if wrong:
            problems.append(f"section 12: Style {key} order names point(s) {wrong} that the "
                            "outline does not have")
    return problems


def replace_verification(text: str, lines: list[str]) -> str:
    marker = f"== {VERIFICATION} =="
    head = text.split(marker)[0].rstrip() + "\n\n"
    return head + marker + "\n" + "\n".join(lines).rstrip() + "\n"


__all__ = ["Fact", "Outline", "Research", "SECTIONS", "Source", "StylePlan", "VERIFICATION",
           "outline_problems", "parse", "read", "replace_verification", "structure_problems",
           "template"]
