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
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from content_automation.content.german import check_text, load_rules
from content_automation.youtube.research import Research
from content_automation.youtube.sources import fact_found
from content_automation.youtube.topic import Style, load_config

TELEPROMPTER = "script_de_teleprompter.txt"  # PRD v6 R7 file names
BILINGUAL = "script_de_en_bilingual.txt"
STORYBOARD = "storyboard.txt"
BRIEF = "brief.md"
ENGLISH_PLACEHOLDER = "<English translation of the German paragraph above>"
# TODO(PENDING, PRD R9.10): the brief was cut off at "Clear placeholders s…". The remaining
# storyboard requirements and the file format (Q6) are unknown: do not guess them. Update
# storyboard_text and docs/v5-implementation-notes.md when they arrive.
STORYBOARD_PENDING = ("PENDING (PRD R9.10): the rest of the storyboard spec and its final "
                      "format are not known yet; this Markdown layout is the interim default.")
_CITATION = re.compile(r"\[S?\d+\]|\(S\d+\)|https?://|www\.|\bQuelle\s*:|\bSource\s*:", re.I)
_LABEL = re.compile(r"^(#+\s|\*\*|hook\b|warnung\b|szene\b|scene\b|abschnitt\b|teil \d|"
                    r"schritt \d+\s*:|regie|notiz|note\b|\[|\()", re.I)
_TRIGRAM = re.compile(r"[a-zäöüß]+")


def paragraphs(text: str) -> list[str]:
    return [re.sub(r"\s*\n\s*", "\n", block.strip())
            for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]


def words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _formula() -> list[dict[str, Any]]:
    path = Path("config/formulas.json")
    found = path if path.is_file() else Path(__file__).resolve().parents[3] / path
    data = json.loads(found.read_text(encoding="utf-8"))
    sections: list[dict[str, Any]] = data["formulas"]["youtube_longform"]["sections"]
    return sections


def brief_text(style: Style, title: str, research: Research) -> str:
    config = load_config()
    low, high = config["targetWords"]
    facts = [f"- {fact} [{', '.join(refs)}]" for fact, refs in research.verified] or [
        "- (no verified facts: run ca youtube check-sources first)"]
    steps = [f"{n}. {step['key']}: {step['what']} ({step['words'][0]}-{step['words'][1]} words)"
             for n, step in enumerate(_formula(), start=1)]
    return "\n".join([
        f"# Brief: style {style.key} {style.name} — {title}",
        "",
        "Internal brief for the writer (English). The teleprompter file is German only.",
        "",
        f"## Approach ({style.name})", style.approach, "",
        "## Formula (PRD R9.6, adapt the weight per topic)", *steps, "",
        "## Verified facts (use only these; numbers exactly as written)", *facts, "",
        "## Rules",
        f"- Write {TELEPROMPTER} in this folder: natural spoken German for a CEO, address the "
        f"viewer with \"{config.get('address', 'Sie')}\", {low}-{high} words (about "
        f"{low // config['wordsPerMinute']}-{high // config['wordsPerMinute']} minutes), clean "
        "paragraphs separated by one empty line, readable line breaks.",
        "- Nothing that must not be read aloud: no headings, labels, step names, notes, stage "
        "directions, citations, [S#], URLs or English.",
        "- Never imply that Roman experienced or witnessed something he did not; no invented "
        "story, number, quotation or event.",
        "- Style C: the scenario is illustrative and says so (\"Stellen Sie sich vor …\").",
        "- The three styles differ in hook, story, delivery and structure, not only in wording.",
        f"- Then run: uv run ca youtube bilingual <BG-ID> (it makes {BILINGUAL} from your "
        "German; fill every English block).",
    ]) + "\n"


def teleprompter_problems(text: str, style_key: str) -> tuple[list[str], list[str]]:
    """(errors, warnings) of one teleprompter file."""
    config = load_config()
    errors: list[str] = []
    warnings: list[str] = []
    blocks = paragraphs(text)
    if not blocks:
        return ["the file is empty"], []
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
    low, high = config["targetWords"]
    count = words(text)
    if not low <= count <= high:
        warnings.append(f"{count} words; the target is {low}-{high} (Q4 default, 10-12 min)")
    return errors, warnings


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


def _trigrams(text: str) -> set[tuple[str, str, str]]:
    tokens = _TRIGRAM.findall(text.lower())
    return set(zip(tokens, tokens[1:], tokens[2:], strict=False))


def _overlap(first: str, second: str) -> float:
    one, two = _trigrams(first), _trigrams(second)
    return len(one & two) / max(1, min(len(one), len(two)))


def similarity_flags(texts: dict[str, str]) -> list[str]:
    """Style pairs whose openings or whole texts are too similar (R9.7)."""
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
    return flags


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def storyboard_text(style: Style, title: str, bg_id: str, teleprompter: str, bilingual: str,
                    research: Research) -> str:
    """One Markdown block per scene (paragraphs merged up to the scene length)."""
    config = load_config()
    per_second = float(config["wordsPerMinute"]) / 60
    shortest = float(config["storyboardSecondsPerScene"][0])
    english = dict(read_bilingual(bilingual))
    scenes: list[list[str]] = []
    for block in paragraphs(teleprompter):
        if scenes and words(" ".join(scenes[-1])) / per_second < shortest:
            scenes[-1].append(block)
        else:
            scenes.append([block])
    lines = [f"# Storyboard: {title}", "",
             f"{bg_id} · style {style.key} {style.name} · for the editing agency (English "
             "explanations; Roman records the German lines)", "",
             f"> {STORYBOARD_PENDING}", "",
             "Fill every <…> before handing it over. Factual visuals cite the research file's "
             "sources [S#].", ""]
    start = 0.0
    for number, blocks in enumerate(scenes, start=1):
        spoken = "\n\n".join(blocks)
        seconds = words(spoken) / per_second
        sources = sorted({ref for fact, refs in research.verified
                          if fact_found(fact, spoken) for ref in refs})
        translated = "\n\n".join(english.get(block, ENGLISH_PLACEHOLDER) for block in blocks)
        lines += [
            f"## Scene {number} · {_clock(start)}–{_clock(start + seconds)} (≈ {seconds:.0f} s)",
            "",
            "**German (spoken by Roman):**", "", spoken, "",
            "**English (translation):**", "", translated, "",
            "**Visual direction:** <what the viewer sees: Roman on camera, B-roll, screen>",
            "",
            "**Graphics, diagrams, animations, screenshots, illustrations:** <what to build>",
            "",
            "**On-screen text (German, exact):** <the exact German text, or none>", "",
            "**On-screen text (English explanation):** <what it says, for the editor>", "",
            "**Sources for factual visuals:** "
            + (", ".join(sources) + " (research file)" if sources else "<[S#] or none>"), "",
            "**Transitions, pacing, supporting footage:** <cut, tempo, music, footage>", "",
            "**Placeholders:** TODO (PENDING spec, PRD R9.10)", "",
        ]
        start += seconds
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["BILINGUAL", "BRIEF", "ENGLISH_PLACEHOLDER", "STORYBOARD", "STORYBOARD_PENDING",
           "TELEPROMPTER",
           "bilingual_problems", "bilingual_text", "brief_text", "paragraphs",
           "read_bilingual", "similarity_flags", "storyboard_text", "teleprompter_problems",
           "words"]
