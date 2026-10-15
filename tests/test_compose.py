"""Live fix: person photos composed in the app (fake OCR, fake rembg, fake face boxes)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from content_automation.core.config import Settings
from content_automation.workflows import compose
from content_automation.workflows.compose import Copy, compose_post, copy_problems, raw_checks

REPO = Path(__file__).resolve().parents[1]
COPY = Copy("Automate The Routine", "One approved workflow, one accountable person.",
            "https://brandedgenius.de")


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(design_system_file=str(REPO / "config" / "design_system.json"),
                         compose_file=str(REPO / "config" / "compose.json"))


def _photo(path: Path) -> Path:
    image = Image.new("RGB", (1024, 1280), (200, 200, 200))
    ImageDraw.Draw(image).ellipse((362, 200, 662, 1280), fill=(40, 40, 60))
    image.save(path)
    return path


def _mask(cover: str) -> Callable[[Image.Image, str], Image.Image]:
    def fake(image: Image.Image, model: str) -> Image.Image:
        mask = Image.new("L", image.size, 0)
        box = (362, 200, 662, 1280) if cover == "body" else (500, 600, 540, 640)
        ImageDraw.Draw(mask).ellipse(box, fill=255)
        return mask
    return fake


def test_raw_checks(tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    photo = _photo(tmp_path / "raw.png")
    monkeypatch.setattr(compose, "_ocr_texts", lambda image, score: [])
    monkeypatch.setattr(compose, "face_boxes", lambda image: [(0.4, 0.15, 0.6, 0.36)])
    assert raw_checks(photo, settings) == []
    monkeypatch.setattr(compose, "_ocr_texts", lambda image, score: ["25%"])
    monkeypatch.setattr(compose, "face_boxes", lambda image: [(0.45, 0.2, 0.55, 0.3)])
    assert raw_checks(photo, settings) == [
        'text in the photo: "25%"', "face height 10% of the image (at least 18%)"]


def test_compose_cutout_then_photo_crop(tmp_path: Path, settings: Settings,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    photo = Image.open(_photo(tmp_path / "raw.png")).convert("RGB")
    monkeypatch.setattr(compose, "face_boxes", lambda image: [(0.4, 0.16, 0.6, 0.36)])
    monkeypatch.setattr(compose, "_human_mask", _mask("body"))
    made = compose_post(photo, settings, "4:5", COPY, None)
    assert made.mode == "cutout" and made.image.size == (1080, 1350)
    assert set(made.boxes) == {"panel", "pill"}
    monkeypatch.setattr(compose, "_human_mask", _mask("tiny"))
    fallback = compose_post(photo, settings, "1:1", COPY, None)
    assert fallback.mode == "photo-crop" and fallback.image.size == (1080, 1080)
    assert "cutout not clean" in fallback.notes[0]


def test_person_copy_limits(settings: Settings) -> None:
    config = compose.compose_config(settings)
    assert copy_problems(COPY, config) == []
    long = Copy("One two three four five six seven eight nine", " ".join(["word"] * 15))
    assert copy_problems(long, config) == [
        "headline: 9 words; a person post allows 8 (shorten it)",
        "sub-line: 15 words; a person post allows 14 (the rest goes in the caption)"]
