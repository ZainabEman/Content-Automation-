"""Phase 7 Step 3: image checks (size, not blank)."""

from pathlib import Path

from PIL import Image, ImageDraw

from content_automation.workflows.image_checks import image_problems


def test_image_checks_size_and_blank(tmp_path: Path) -> None:
    good = Image.new("RGB", (1024, 1024), (20, 80, 200))
    ImageDraw.Draw(good).rectangle((100, 100, 600, 600), fill=(240, 240, 240))
    good.save(tmp_path / "good.png")
    Image.new("RGB", (300, 300), (255, 255, 255)).save(tmp_path / "bad.png")
    assert image_problems(tmp_path / "good.png") == []
    assert image_problems(tmp_path / "bad.png") == ["300x300 is smaller than 512 px",
                                                    "blank (one flat colour)"]
