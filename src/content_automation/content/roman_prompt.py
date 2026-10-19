"""Roman image prompts for Higgsfield Soul 2.0 (2026-10-20 guidelines).

Every image of Roman is made by Codex with the Higgsfield plugin (model Soul 2.0) from the saved
Higgsfield character; the prompt is built here from config/roman_image_guidelines.json: fixed
rules (character reference, framing, gaze, wardrobe, lighting, negative space, colour, camera,
no text) plus one side (S-R Roman right, S-L Roman left, mirrored in the words, never by
flipping the image), one background (BG-1..3), one pose (P-1..3; its wording per background is
data) and one hologram style (H-1..3): 54 combinations, id "S-L/BG-2/P-3/H-1".

Rotation per platform over the Roman images (package.json `romanCombination`, newest first):
never the background, pose or hologram style of the previous one, never the same side three
times in a row, never a full combination of the last 12; seeded by the Content ID. An override
("use S-L BG-1 P-2 H-3") wins when it is a valid combination.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from pathlib import Path
from typing import Any

CONFIG_FILE = Path("config/roman_image_guidelines.json")
PACKAGE_KEY = "romanCombination"
# PRD v5 R6.7 (EU AI Act Art. 50): the label of every generated image of Roman
AI_DISCLOSURE = "KI-generiertes Bild (Roman, erstellt mit einem KI-Modell)"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
# also inside a request: "use S-L BG-1 P-2 H-3", "as S-L/BG-1/P-2/H-3"
_ID = re.compile(r"(?<![\w-])(S-[RL])[\s/]+(BG-[1-3])[\s/]+(P-[1-3])[\s/]+(H-[1-3])(?![\w-])",
                 re.I)


class RomanPromptError(ValueError):
    """A combination or the guideline file is invalid."""


@dataclass(frozen=True)
class Combination:
    side: str  # S-R or S-L
    background: str  # BG-1..3
    pose: str  # P-1..3
    hologram: str  # H-1..3

    @property
    def id(self) -> str:
        return f"{self.side}/{self.background}/{self.pose}/{self.hologram}"

    @property
    def roman_right(self) -> bool:
        return self.side == "S-R"


@lru_cache(maxsize=4)
def load_guidelines(path: Path = CONFIG_FILE) -> dict[str, Any]:
    found = path if path.is_file() else _PROJECT_ROOT / path
    data = json.loads(found.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RomanPromptError(f"{path} must be a JSON object")
    return data


def parse_combination(text: str) -> Combination:
    """"S-L/BG-2/P-3/H-1", "S-L BG-2 P-3 H-1" or "use S-L BG-2 P-3 H-1" (any case)."""
    match = _ID.search(text or "")
    if match is None:
        raise RomanPromptError(f'"{text}" is not a Roman combination like S-L/BG-1/P-2/H-3')
    side, background, pose, hologram = (part.upper() for part in match.groups())
    return Combination(side, background, pose, hologram)


def is_combination(text: str | None) -> bool:
    return bool(text) and _ID.search(str(text)) is not None


def all_combinations(guidelines: dict[str, Any] | None = None) -> list[Combination]:
    data = guidelines or load_guidelines()
    return [Combination(*parts) for parts in product(
        sorted(data["sides"], reverse=True), sorted(data["backgrounds"]), sorted(data["poses"]),
        sorted(data["holograms"]))]


def character_token(guidelines: dict[str, Any] | None = None, name: str | None = None) -> str:
    """The character reference that opens every prompt ("@" + the configured name)."""
    higgsfield = (guidelines or load_guidelines())["higgsfield"]
    return str(higgsfield["characterToken"]).format(name=name or higgsfield["characterName"])


def build_prompt(combination: Combination, *, token: str | None = None,
                 guidelines: dict[str, Any] | None = None) -> str:
    """The Soul 2.0 prompt of one combination (paragraphs separated by an empty line)."""
    data = guidelines or load_guidelines()
    try:
        side = data["sides"][combination.side]
        background = data["backgrounds"][combination.background]
        pose = data["poses"][combination.pose]
        hologram = data["holograms"][combination.hologram]
    except KeyError as error:
        raise RomanPromptError(f"{combination.id}: unknown part {error}") from None
    words = {"side": side["side"], "other": side["other"]}
    values = {
        **words,
        "token": token or character_token(data),
        "verb": pose["verb"],
        "pose": pose["byBackground"][combination.background],
        "expression": pose["expression"],
        "setting": str(background["setting"]).format(**words),
        "hologram": str(hologram["text"]).format(**words, surface=background["surface"]),
        "fade": background["fade"],
        "bans": ", ".join(background["bans"]),
        "tail": background["tail"],
        "subject": data["higgsfield"]["subjectName"],
        "holoWord": hologram["word"],
        "blur": background["blur"],
    }
    fixed = data["fixed"]
    paragraphs = [" ".join(str(fixed[name]).format(**values) for name in group)
                  for group in fixed["paragraphs"]]
    return "\n\n".join(paragraphs)


def history(packages_dir: Path, platform: str, *, exclude: Path | None = None) -> list[str]:
    """The Roman combinations of the newest packages on the platform, newest first."""
    found: list[tuple[str, str]] = []
    for path in packages_dir.glob("*/package.json"):
        if exclude is not None and path.parent.resolve() == exclude.resolve():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("platform") == platform and is_combination(
                str(data.get(PACKAGE_KEY) or "")):
            found.append((str(data.get("createdAt") or ""), str(data[PACKAGE_KEY])))
    return [value for _, value in sorted(found, reverse=True)]


def allowed(candidate: Combination, recent: list[Combination],
            guidelines: dict[str, Any] | None = None) -> bool:
    rules = (guidelines or load_guidelines())["rotation"]
    if recent:
        last = recent[0]
        parts = {"background": (candidate.background, last.background),
                 "pose": (candidate.pose, last.pose),
                 "hologram": (candidate.hologram, last.hologram)}
        if any(parts[name][0] == parts[name][1] for name in rules["noRepeatOfPrevious"]):
            return False
    same = int(rules["maxSameSideInARow"])
    if len(recent) >= same and all(item.side == candidate.side for item in recent[:same]):
        return False
    window = {item.id for item in recent[:int(rules["noFullRepeatWithin"])]}
    return candidate.id not in window


def pick_combination(seed: str, recent_ids: list[str], *, override: str | None = None,
                     guidelines: dict[str, Any] | None = None) -> tuple[Combination, str]:
    """The combination of a new Roman image and why (one short reason)."""
    if override:
        return parse_combination(override), "as asked"
    recent = [parse_combination(value) for value in recent_ids if is_combination(value)]
    options = [item for item in all_combinations(guidelines) if allowed(item, recent, guidelines)]
    if not options:  # cannot happen with 54 combinations; never silently repeat the last one
        options = [item for item in all_combinations(guidelines)
                   if not recent or item.id != recent[0].id]
    chosen = random.Random(f"roman|{seed}").choice(options)
    reason = "first Roman image on this platform" if not recent else (
        f"rotated: not like {recent[0].id}")
    return chosen, reason


__all__ = ["AI_DISCLOSURE", "CONFIG_FILE", "Combination", "PACKAGE_KEY", "RomanPromptError",
           "all_combinations", "allowed", "build_prompt", "character_token", "history",
           "is_combination", "load_guidelines", "parse_combination", "pick_combination"]
