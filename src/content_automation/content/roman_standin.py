"""A drawn stand-in for a Higgsfield image of Roman (previews and offline tests only).

Near-black navy background, a soft royal-blue glow, a figure with a skin-tone face and hands, a
white shirt and a navy suit at the planned edge (the rightmost or leftmost ~18 %), and small
sky-blue hologram dots in his third. Never a real person; never shown as the final image.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

NAVY = (5, 9, 22)
SUIT = (24, 34, 62)
SKIN = (226, 178, 146)
SHIRT = (242, 242, 240)
GLOW = (0, 75, 160)
HOLO = (105, 191, 248)


def stand_in(size: tuple[int, int], side: str = "S-R", pose: str = "P-1",
             offset: float = 0.0) -> Image.Image:
    """`offset` moves the figure toward the middle (a share of the width): failing fixtures."""
    width, height = size
    image = Image.new("RGB", size, NAVY)
    glow = Image.new("L", size, 0)
    right = side == "S-R"
    centre = (0.9 - offset if right else 0.1 + offset) * width
    ImageDraw.Draw(glow).ellipse((centre - width * 0.25, height * 0.15, centre + width * 0.25,
                                  height * 0.85), fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(width // 15))
    image.paste(Image.new("RGB", size, GLOW), (0, 0), glow)
    draw = ImageDraw.Draw(image)
    unit = width * 0.055
    head_y = height * (0.34 if pose == "P-1" else 0.28)
    draw.rounded_rectangle((centre - unit * 1.9, head_y + unit * 1.6, centre + unit * 1.9,
                            height * 1.02), radius=int(unit), fill=SUIT)
    draw.polygon([(centre - unit * 0.6, head_y + unit * 1.6),
                  (centre + unit * 0.6, head_y + unit * 1.6),
                  (centre, head_y + unit * 4.2)], fill=SHIRT)
    draw.ellipse((centre - unit * 0.75, head_y - unit * 0.2, centre + unit * 0.75,
                  head_y + unit * 1.7), fill=SKIN)
    hands_y = height * {"P-1": 0.8, "P-2": 0.72, "P-3": 0.62}.get(pose, 0.75)
    for dx in (-0.8, 0.5) if pose != "P-2" else (-1.4,):
        draw.ellipse((centre + unit * dx - unit * 0.35, hands_y, centre + unit * dx + unit * 0.35,
                      hands_y + unit * 0.6), fill=SKIN)
    third = (int(width * 2 / 3), width) if right else (0, int(width / 3))
    for index in range(5):
        x = third[0] + (third[1] - third[0]) * (0.15 + 0.15 * index)
        y = height * (0.18 + 0.05 * (index % 2))
        draw.ellipse((x - 9, y - 9, x + 9, y + 9), outline=HOLO, width=3)
    return image


__all__ = ["stand_in"]
