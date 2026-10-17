"""Phase D step 6: Roman's identity rules (config/design_directions.json `roman`).

Real photos first: FD-1 cuts out one of the approved green-screen photos (identity exact, nothing
generated), rotated so two founder posts in a row do not reuse it; FD-2 uses an approved
portrait when one exists, else the LoRA. The LoRA (FD-2, FD-3, comfyui only, never swapped) gets a
prompt built from the pools, seeded by the Content ID; a prompt with a blocked prop, without the
trigger word, the "alone" rule or "no text" is refused before any paid call. Every LoRA image
waits for the person check; the identity sheet puts it beside two approved real photos, and the
verdict is recorded with `ca job review --person pass|fail` (no automatic pass).
"""

from __future__ import annotations

import random
import re
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from content_automation.content.directions import Direction, Layout, RomanRules

SHEET_HEIGHT = 900
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FONT = _PROJECT_ROOT / "assets" / "fonts" / "Jost-Medium.ttf"
_QUIET_LUXURY_SHARE = 0.25  # D-6: quiet luxury allowed besides business settings


class RomanError(ValueError):
    """A Roman rule is broken: a missing approved photo, a bad prompt or LoRA strength."""


def approved_photos(rules: RomanRules, identity_dir: Path, *, portrait: bool = False) -> list[Path]:
    """The approved real photos that exist (portrait: the FD-2 list, may be empty)."""
    names = rules.portrait_photos if portrait else rules.approved_photos
    found = [identity_dir / name for name in names if (identity_dir / name).is_file()]
    if not portrait and not found:
        raise RomanError(f"none of the approved photos ({', '.join(names)}) is in "
                         f"{identity_dir}: copy the identity set onto this machine")
    return found


def pick_real_photo(rules: RomanRules, identity_dir: Path, *, seed: str,
                    previous: str | None = None, portrait: bool = False) -> Path | None:
    """One approved real photo, not the one of the previous founder post when another exists."""
    photos = approved_photos(rules, identity_dir, portrait=portrait)
    if not photos:
        return None
    pool = [photo for photo in photos if photo.name != previous] or photos
    return random.Random(f"roman-photo|{seed}").choice(pool)


def text_side(layout: Layout) -> str:
    """Where the layout's main text sits, for the prompt's empty area ({space})."""
    boxes = [zone.box for zone in layout.zones.values() if zone.kind == "text"]
    if not boxes:
        return "above his head"
    middle_x = sum((box[0] + box[2]) / 2 for box in boxes) / len(boxes)
    middle_y = sum((box[1] + box[3]) / 2 for box in boxes) / len(boxes)
    if middle_y < 0.4:
        return "in the upper part of the frame"
    if middle_x < 0.45:
        return "on the left side of the frame"
    if middle_x > 0.55:
        return "on the right side of the frame"
    return "in the lower part of the frame"


def roman_prompt(direction: Direction, layout: Layout, rules: RomanRules, *, seed: str) -> str:
    """The LoRA prompt of a founder direction, from the pools (the same seed, the same prompt)."""
    if direction.visual.subject != "roman_lora":
        raise RomanError(f"{direction.id} does not use Roman's LoRA")
    rng = random.Random(f"roman|{direction.id}|{seed}")
    luxury = rng.random() < _QUIET_LUXURY_SHARE and rules.settings.get("quiet_luxury")
    settings = luxury or rules.settings["business"]
    prompt = direction.visual.prompt.format(
        prefix=rules.prefix, outfit=rng.choice(rules.outfits), angle=rng.choice(rules.angles),
        expression=rng.choice(rules.expressions), setting=rng.choice(settings),
        alone=rules.alone, noTextSurfaces=rules.no_text_surfaces, space=text_side(layout))
    problems = prompt_problems(prompt, rules)
    if problems:
        raise RomanError(f"{direction.id} prompt: {'; '.join(problems)}")
    return prompt


def prompt_problems(prompt: str, rules: RomanRules) -> list[str]:
    """Free checks of a Roman prompt before any paid call."""
    lowered = prompt.lower()
    problems = [f'blocked prop "{prop}" (D-6)' for prop in rules.blocked_props
                if re.search(rf"(?<![a-z]){re.escape(prop.lower())}(?![a-z])", lowered)]
    if not lowered.startswith(rules.prefix.lower()):
        problems.append(f'it must start with the trigger "{rules.prefix}"')
    if rules.alone.lower() not in lowered:
        problems.append("the 'alone' rule is missing (one person in focus)")
    if "no text" not in lowered:
        problems.append('"no text" is missing')
    if "{" in prompt or "}" in prompt:
        problems.append("an unfilled {placeholder}")
    return problems


def check_strength(strength: float, rules: RomanRules) -> None:
    low, high = rules.lora_strength
    if not low <= strength <= high:
        raise RomanError(f"LoRA strength {strength} is outside {low}-{high} "
                         "(config/design_directions.json roman.loraStrength)")


def identity_sheet(generated: Path, photos: Sequence[Path], target: Path) -> Path:
    """The generated image beside approved real photos, one PNG for the person check."""
    tiles: list[tuple[str, Image.Image]] = []
    with Image.open(generated) as image:
        tiles.append(("GENERATED", ImageOps.contain(image.convert("RGB"),
                                                   (SHEET_HEIGHT, SHEET_HEIGHT))))
    for photo in photos:
        with Image.open(photo) as image:
            upright = ImageOps.exif_transpose(image).convert("RGB")
            tiles.append((f"REAL {photo.name}", ImageOps.contain(upright,
                                                                (SHEET_HEIGHT, SHEET_HEIGHT))))
    gap, label_h = 24, 64
    width = sum(tile.width for _, tile in tiles) + gap * (len(tiles) + 1)
    sheet = Image.new("RGB", (width, SHEET_HEIGHT + label_h + 2 * gap), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(_FONT), 34)
    x = gap
    for label, tile in tiles:
        sheet.paste(tile, (x, gap + label_h + (SHEET_HEIGHT - tile.height) // 2))
        draw.text((x + tile.width / 2, gap + label_h / 2), label, font=font, fill=(0, 75, 160),
                  anchor="mm")
        x += tile.width + gap
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, format="PNG", optimize=True)
    return target


__all__ = ["RomanError", "approved_photos", "check_strength", "identity_sheet",
           "pick_real_photo", "prompt_problems", "roman_prompt", "text_side"]
