"""German line breaks for the founder overlays (GERMAN_CONTENT_AND_IMAGE_WORKFLOW_PRD.md Phase 3,
P3-R2/P3-R3). The algorithm of postcanvas (MIT) is ported, not installed: a balanced wrap that
takes the fewest lines that fit and, among them, the least squared slack (a headline counts its
last line, body text leaves it free), plus widow control.

German rules on top:
- never break after an article, a possessive or a demonstrative (der, eine, Ihre, diese …) or a
  preposition (mit, für, im …): article and noun, preposition and object stay on one line;
- never break after a number (30 Prozent, 120.000 Euro, drei Fragen): number and unit or noun
  stay together;
- never inside a word in a headline; in body text only at a soft hyphen (U+00AD) or a hyphen
  the writer set, and only when the text fits no other way (`hyphenate`); a "KI-…" compound
  never breaks;
- a headline of three words or more never ends on a one-word line, unless every line holds one
  word (a stack).
`wrap` returns None when no wrap fits: the caller shrinks the size or reports "text too long".
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass


def _set(words: str) -> frozenset[str]:
    return frozenset(words.split())


ARTICLES = _set(
    "der die das den dem des ein eine einen einem einer eines kein keine keinen keinem keiner "
    "keines mein meine meinen meinem meiner meines dein deine deinen deinem deiner deines ihr "
    "ihre ihren ihrem ihrer ihres sein seine seinen seinem seiner seines unser unsere unseren "
    "unserem unserer unseres euer eure euren eurem eurer eures dieser diese dieses diesen "
    "diesem jeder jede jedes jeden jedem welche welcher welches")
PREPOSITIONS = _set(
    "ab an am ans auf aufs aus bei beim bis durch durchs für fürs gegen hinter im in ins mit "
    "nach neben ohne pro per seit statt trotz um über unter vom von vor während wegen zu zum "
    "zur zwischen laut dank gemäß außer innerhalb außerhalb")
NUMBER_WORDS = _set(
    "zwei drei vier fünf sechs sieben acht neun zehn elf zwölf zwanzig dreißig vierzig fünfzig "
    "hundert tausend")
_NUMBER = re.compile(r"^[+-]?\d[\d.,]*%?$")
_EDGES = "\"'„“”‚‘’«»()[]*.,:;!?"


@dataclass(frozen=True)
class Piece:
    """One word or one part of a hyphenated word, measured at the size being tried."""

    text: str
    width: float
    glue: bool = False  # continues the word before it (no space between)
    breakable: bool = False  # a line may end after it inside its word (soft hyphen or "-")
    hyphen: float = 0.0  # the "-" a soft hyphen shows when the line ends here


def _plain(text: str) -> str:
    return text.strip(_EDGES).lower()


def keeps_next(word: str) -> bool:
    """True when no line may end after this word (an article, a preposition or a number)."""
    plain = _plain(word)
    return plain in ARTICLES or plain in PREPOSITIONS or plain in NUMBER_WORDS or bool(
        _NUMBER.match(plain))


def _words(pieces: Sequence[Piece]) -> list[tuple[int, int, str]]:
    """(first piece, end piece, text) of every word."""
    found: list[tuple[int, int, str]] = []
    for index, piece in enumerate(pieces):
        if piece.glue and found:
            start, _, text = found[-1]
            found[-1] = (start, index + 1, text + piece.text)
        else:
            found.append((index, index + 1, piece.text))
    return found


def break_points(pieces: Sequence[Piece], *, hyphenate: bool) -> set[int]:
    """The piece indexes a line may end before (0 < index < len)."""
    words = _words(pieces)
    owner = {index: number for number, (start, end, _) in enumerate(words)
             for index in range(start, end)}
    allowed: set[int] = set()
    for index in range(1, len(pieces)):
        before = words[owner[index - 1]]
        if pieces[index].glue:  # inside a word: a hyphen the writer set, last resort, never KI-
            if hyphenate and pieces[index - 1].breakable and not before[2].upper().startswith(
                    "KI-"):
                allowed.add(index)
        elif not keeps_next(before[2]):
            allowed.add(index)
    return allowed


def wrap(pieces: Sequence[Piece], width: float, space: float, max_lines: int, *,
         headline: bool, hyphenate: bool = False,
         lines_wanted: int | None = None) -> list[tuple[int, int]] | None:
    """The lines as (start, end) piece ranges, or None when nothing fits in max_lines
    (lines_wanted: exactly that many lines)."""
    count = len(pieces)
    if count == 0:
        return []
    allowed = break_points(pieces, hyphenate=hyphenate)
    starts = [0, *sorted(allowed)]
    ends = {*allowed, count}

    def line_width(start: int, end: int) -> float:
        total = sum(piece.width for piece in pieces[start:end])
        total += space * sum(1 for piece in pieces[start + 1:end] if not piece.glue)
        if end < count and pieces[end].glue:
            total += pieces[end - 1].hyphen
        return total

    def word_count(start: int, end: int) -> int:
        return sum(1 for index in range(start, end) if index == start or not pieces[index].glue)

    total_words = word_count(0, count)
    widow_rule = headline and total_words >= 3
    for lines in [lines_wanted] if lines_wanted else range(1, max_lines + 1):
        # best[(end, used)] = (cost, previous end): the first `end` pieces set in `used` lines
        best: dict[tuple[int, int], tuple[float, int]] = {(0, 0): (0.0, -1)}
        for used in range(1, lines + 1):
            for start in starts:
                previous = best.get((start, used - 1))
                if previous is None:
                    continue
                for end in sorted(e for e in ends if e > start):
                    filled = line_width(start, end)
                    if filled > width:
                        break
                    last = end == count
                    if last != (used == lines):
                        continue
                    if last and widow_rule and word_count(start, end) < 2 and (
                            lines != total_words):
                        continue
                    slack = width - filled
                    cost = previous[0] + (0.0 if last and not headline else slack * slack)
                    if (end, used) not in best or cost < best[(end, used)][0]:
                        best[(end, used)] = (cost, start)
        if (count, lines) in best:
            ranges: list[tuple[int, int]] = []
            end, used = count, lines
            while used:
                start = best[(end, used)][1]
                ranges.append((start, end))
                end, used = start, used - 1
            return ranges[::-1]
    return None


__all__ = ["ARTICLES", "NUMBER_WORDS", "PREPOSITIONS", "Piece", "break_points", "keeps_next",
           "wrap"]
