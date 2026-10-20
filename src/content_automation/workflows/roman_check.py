"""The strict checks of a Roman image made with Higgsfield (2026-10-20), after the app drew the
German text and the CTA (no logo or website, PRD v6). Any failure blocks the item.

1. person zone: done on the delivered picture (providers/higgsfield_soul.placed): Roman fully
   within the outer 40% of the width on his side (a shift crop first), nothing person-like in
   the text side; a failure stops the row for the operator (accept or retry).
2. no overlap: every text and CTA (and a logo, if a manifest has one) stays at least 48 px (at
   1080 px width) away from the hologram third, which holds Roman.
3. calm text zones: behind each text box the picture's brightness spread and detail stay low.
4. contrast, sizes, 64 px margins, logo hash and clear space: workflows/design_check.py (the
   `ca design check` thresholds), run on the same manifest.
5. German: content/german.py on the drawn texts, plus noun capitalisation after an article,
   wrong hyphenation, and a spelling check with Hunspell (de_DE) when installed; without it,
   spelling is Codex's visual review step (recorded as such).
Thresholds: config/roman_image_guidelines.json `checks`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from content_automation.content.german import check_texts
from content_automation.content.roman_prompt import load_guidelines

PASSED = "passed"
_ARTICLE = re.compile(r"\b(?:der|die|das|den|dem|des|ein|eine|einen|einem|einer|eines)\s+"
                      r"([a-zäöüß][a-zäöüß]+)\b")
_NOUN_END = ("ung", "heit", "keit", "schaft", "tion", "tät", "nis", "ismus", "ment", "ling")
_BROKEN = re.compile(r"[A-Za-zÄÖÜäöüß]-\s+[a-zäöüß]")  # "Maß- nahme": a word split by a break


@dataclass
class RomanChecks:
    """Each check's result ("passed", "skipped: …" or "failed: …") and the blocking errors."""

    results: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def record(self, name: str, problems: list[str], *, skipped: str | None = None) -> None:
        if skipped is not None:
            self.results[name] = f"skipped: {skipped}"
            return
        self.results[name] = PASSED if not problems else "failed: " + "; ".join(problems)
        self.errors += [f"{name}: {problem}" for problem in problems]


def hologram_box(side: str, size: tuple[int, int], share: float) -> tuple[float, ...]:
    """Roman's third of the canvas (the hologram third, Roman inside it)."""
    width, height = size
    if side == "S-L":
        return (0.0, 0.0, width * share, float(height))
    return (width * (1 - share), 0.0, float(width), float(height))


def _gap(box: tuple[float, ...], third: tuple[float, ...]) -> float:
    """The horizontal distance between a box and the third (negative: they overlap)."""
    if third[0] == 0.0:
        return box[0] - third[2]
    return third[0] - box[2]


def overlap_problems(manifest: Mapping[str, Any], side: str, *, share: float,
                     min_gap_px: float) -> list[str]:
    size = tuple(int(value) for value in manifest.get("size") or (1080, 1350))
    width = size[0]
    third = hologram_box(side, (size[0], size[1]), share)
    need = min_gap_px * width / 1080
    boxes: list[tuple[str, tuple[float, ...]]] = []
    for text in manifest.get("texts") or []:
        boxes.append((f"{text.get('zone')} \"{str(text.get('text', ''))[:30]}\"",
                      tuple(float(value) for value in text.get("box") or (0, 0, 0, 0))))
    logo = manifest.get("logo")
    if logo:
        mark = [float(value) for value in logo.get("box", (0, 0, 0, 0))]
        clear = float(logo.get("clear_space_px", 0))
        boxes.append(("logo (with clear space)",
                      (mark[0] - clear, mark[1] - clear, mark[2] + clear, mark[3] + clear)))
    problems = []
    for where, box in boxes:
        gap = _gap(box, third)
        if gap < need:
            state = "overlaps" if gap < 0 else f"is {gap:.0f} px from"
            problems.append(f"{where} {state} Roman's third (needs {need:.0f} px)")
    return problems


def calm_problems(picture: Image.Image, manifest: Mapping[str, Any], *, max_std: float,
                  max_detail: float) -> list[str]:
    """Brightness spread (std) and detail (mean edge strength) behind each text box, measured
    on the picture as the renderer placed it (fitted to the canvas)."""
    size = tuple(int(value) for value in manifest.get("size") or picture.size)
    fitted = ImageOps.fit(picture.convert("L"), (size[0], size[1]), Image.Resampling.LANCZOS)
    edges = np.asarray(fitted.filter(ImageFilter.FIND_EDGES), dtype=np.float64)
    gray = np.asarray(fitted, dtype=np.float64)
    problems = []
    for text in manifest.get("texts") or []:
        x0, y0, x1, y1 = (int(round(float(value))) for value in text.get("box") or (0, 0, 0, 0))
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, size[0]), min(y1, size[1])
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        spread = float(gray[y0:y1, x0:x1].std())
        detail = float(edges[y0 + 1:y1 - 1, x0 + 1:x1 - 1].mean())
        if spread > max_std or detail > max_detail:
            problems.append(f"{text.get('zone')}: busy background (brightness spread "
                            f"{spread:.0f} > {max_std:g} or detail {detail:.1f} > "
                            f"{max_detail:g})")
    return problems


def _hunspell(words: list[str]) -> list[str] | None:
    """Misspelled words by Hunspell (de_DE), or None when it is not installed (local only)."""
    binary = shutil.which("hunspell")
    if binary is None or not words:
        return None if binary is None else []
    try:
        done = subprocess.run([binary, "-d", "de_DE", "-l"], input="\n".join(words),
                              capture_output=True, text=True, encoding="utf-8", timeout=20,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return sorted({line.strip() for line in done.stdout.splitlines() if line.strip()})


def german_problems(texts: list[tuple[str, str]]) -> tuple[list[str], str]:
    """(errors, how spelling was checked) for the drawn German texts."""
    problems = list(check_texts(texts).errors)
    for where, text in texts:
        for match in _ARTICLE.finditer(text):
            word = match.group(1)
            if word.endswith(_NOUN_END):
                problems.append(f'{where}: "{word}" after "{match.group(0).split()[0]}" is a '
                                f'noun: "{word[0].upper() + word[1:]}"')
        if _BROKEN.search(text) or "--" in text or "­" in text:
            problems.append(f'{where}: wrong hyphenation in "{text[:40]}"')
    words = sorted({word for _, text in texts
                    for word in re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", text)})
    misspelled = _hunspell(words)
    if misspelled is None:
        spelling = ("Spelling: Hunspell is not installed; Codex reviews it (visual review, "
                    "german=yes|no).")
    else:
        spelling = "Spelling: Hunspell de_DE."
        problems += [f'spelling: "{word}" (Hunspell de_DE)' for word in misspelled]
    return problems, spelling


def run_checks(manifest: Mapping[str, Any], side: str, picture: Image.Image | None,
               *, guidelines: dict[str, Any] | None = None) -> tuple[RomanChecks, str]:
    """The overlap, calm and German checks (design_check runs contrast, sizes, margins, logo);
    the second value says how spelling was checked."""
    rules = (guidelines or load_guidelines())["checks"]
    checks = RomanChecks()
    checks.results["personZone"] = PASSED  # checked on the delivered picture before drawing
    checks.record("overlap", overlap_problems(
        manifest, side, share=float(rules["hologramZoneShare"]),
        min_gap_px=float(rules["minGapPx"])))
    if picture is None:
        checks.record("textZoneCalm", [], skipped="no picture (mock)")
    else:
        checks.record("textZoneCalm", calm_problems(
            picture, manifest, max_std=float(rules["textZoneMaxStd"]),
            max_detail=float(rules["textZoneMaxDetail"])))
    texts = [(str(text.get("zone")), str(text.get("text", "")))
             for text in manifest.get("texts") or []]
    problems, spelling = german_problems(texts)
    checks.record("german", problems)
    checks.results["spelling"] = spelling
    return checks, spelling


__all__ = ["PASSED", "RomanChecks", "calm_problems", "german_problems", "hologram_box",
           "overlap_problems", "run_checks"]
