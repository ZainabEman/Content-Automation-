"""The research TXT of a topic (PRD v5 R9.4): template, parser and the free structure check.

Plain UTF-8. Sections start with "== <number>. <TITLE> ==". Sources are numbered [S1], [S2] …:
section 5 lists "[S1] Title | Publisher | YYYY-MM-DD", section 6 "[S1] https://…". Facts
(sections 7 and 11a) are lines "- <fact> [S1]"; quotations (section 8) are lines
"- \"<quote>\" — <name, role> [S2]". The VERIFICATION section is written by
`ca youtube check-sources` and replaced on every run. Nothing here is invented: the agent fills
the template from sources it opened; the check refuses placeholders and facts without a source.
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
]
VERIFICATION = "VERIFICATION (written by ca youtube check-sources)"
_HEADING = re.compile(r"^==\s*(?:(\w+)\.\s*)?(.+?)\s*==\s*$", re.M)
_REF = re.compile(r"\[S(\d+)\]")
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
class Research:
    sections: dict[str, str]
    sources: dict[str, Source] = field(default_factory=dict)
    facts: list[tuple[str, list[str]]] = field(default_factory=list)  # (text, source ids)
    verified: list[tuple[str, list[str]]] = field(default_factory=list)
    quotes: list[tuple[str, list[str]]] = field(default_factory=list)  # (quote, source ids)


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
        "7": "- <a statistic or fact, exactly as the source states it> [S1]",
        "8": "- \"<an exact quotation from the page>\" — <name, role> [S2]\n"
             "(or: none)",
        "9": "<claims that need careful wording, and why>",
        "10": "<where sources disagree, what is unknown, the limits of each source>",
        "11a": "- <a fact the sources state directly> [S1]",
        "11b": "<what it means: clearly marked as interpretation>",
        "11c": "<practical, responsible solutions for German viewers>",
    }
    lines = [f"RESEARCH: {title}", f"BG ID: {bg_id} | Month: {month} | Slug: {slug_text}",
             "Rules: real incidents and documented problems only; never invent a source, URL, "
             "title, quotation, number or event; every fact names its [S#].", ""]
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
            rows.append((_REF.sub("", line.lstrip("- ")).strip(),
                         [f"S{n}" for n in _REF.findall(line)]))
    return rows


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


def replace_verification(text: str, lines: list[str]) -> str:
    marker = f"== {VERIFICATION} =="
    head = text.split(marker)[0].rstrip() + "\n\n"
    return head + marker + "\n" + "\n".join(lines).rstrip() + "\n"


__all__ = ["Research", "SECTIONS", "Source", "VERIFICATION", "parse", "read",
           "replace_verification", "structure_problems", "template"]
