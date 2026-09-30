import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.references import (
    ReferenceLibraryError,
    assets_by_type,
    list_sets,
    load_set,
    scan,
    select_identity_refs,
    set_primary,
)


def make_image(
    path: Path,
    size: tuple[int, int] = (600, 800),
    *,
    mode: str = "RGB",
    orientation: int | None = None,
    color: int = 0,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fill = ((color * 41) % 256, (color * 97) % 256, 150, 128)[: len(mode)]
    image = Image.new(mode, size, fill)
    if orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = orientation
        image.save(path, exif=exif)
    else:
        image.save(path)
    return path


def identity_set(root: Path, count: int = 6) -> Path:
    folder = root / "identity" / "person_01"
    for index in range(1, count + 1):
        make_image(folder / f"{index}.jpg", color=index)
    return folder


def asset(set_file: Path, name: str) -> dict[str, object]:
    data = json.loads(set_file.read_text(encoding="utf-8"))
    return next(a for a in data["assets"] if a["file"] == name)


def test_scan_detects_types_sets_and_skips(tmp_path: Path) -> None:
    identity_set(tmp_path, 2)
    make_image(tmp_path / "brand" / "logo" / "logo.png", (300, 300), mode="RGBA")
    make_image(tmp_path / "creative" / "carousels" / "c1" / "slide.jpg", (1080, 1350))
    videos = tmp_path / "creative" / "carousels" / "videos_only"
    videos.mkdir(parents=True)
    (videos / "a.mp4").write_bytes(b"video")
    (videos / "b.pdf").write_bytes(b"%PDF")
    (tmp_path / "product").mkdir()
    (tmp_path / "misc").mkdir()

    report = scan(tmp_path)

    assert {(s.set_id, s.type) for s in report.sets} == {
        ("identity/person_01", "identity"),
        ("brand/logo", "brand"),
        ("creative/carousels/c1", "creative"),
    }
    assert [(s.path, s.reason) for s in report.skipped] == [
        (
            "creative/carousels/videos_only",
            "no JPG/PNG/WebP images (1 mp4, 1 pdf); run `ca refs frames` to use video frames",
        )
    ]
    assert any("misc" in warning for warning in report.warnings)
    assert (tmp_path / "identity" / "person_01" / "set.json").is_file()
    assert not (videos / "set.json").exists()


def test_asset_ids_are_stable_content_hashes(tmp_path: Path) -> None:
    folder = identity_set(tmp_path, 2)
    expected = hashlib.sha256((folder / "1.jpg").read_bytes()).hexdigest()[:12]

    first = scan(tmp_path).sets[0]
    (folder / "1.jpg").rename(folder / "renamed.jpg")
    second = scan(tmp_path).sets[0]

    assert first.assets[0].asset_id == expected
    assert {a.asset_id for a in first.assets} == {a.asset_id for a in second.assets}


def test_rejections_have_reasons_and_originals_stay(tmp_path: Path) -> None:
    folder = identity_set(tmp_path, 1)
    make_image(folder / "small.jpg", (400, 900))
    (folder / "vector.svg").write_text("<svg/>", encoding="utf-8")
    (folder / "doc.pdf").write_bytes(b"%PDF-1.4")
    (folder / "broken.jpg").write_bytes(b"not an image")
    (folder / "copy.jpg").write_bytes((folder / "1.jpg").read_bytes())
    make_image(tmp_path / "brand" / "logo" / "ok.png", (300, 300))
    make_image(tmp_path / "brand" / "logo" / "tiny.png", (200, 300))

    scan(tmp_path)

    reasons = {name: asset(folder / "set.json", name)["reason"] for name in
               ("small.jpg", "vector.svg", "doc.pdf", "broken.jpg", "copy.jpg")}
    assert "too small: 400x900px" in str(reasons["small.jpg"])
    assert "SVG" in str(reasons["vector.svg"])
    assert "PDF" in str(reasons["doc.pdf"])
    assert "cannot be read" in str(reasons["broken.jpg"])
    assert reasons["copy.jpg"] == "duplicate of 1.jpg"
    logo = tmp_path / "brand" / "logo" / "set.json"
    assert asset(logo, "ok.png")["status"] == "ok"
    assert "256px" in str(asset(logo, "tiny.png")["reason"])
    assert all((folder / name).exists() for name in reasons)


def test_resized_copies_fix_orientation_and_limit_size(tmp_path: Path) -> None:
    folder = tmp_path / "identity" / "p"
    make_image(folder / "big.jpg", (3000, 2000))
    make_image(folder / "rotated.jpg", (800, 600), orientation=6)
    make_image(folder / "alpha.png", (700, 700), mode="RGBA")

    scan(tmp_path)
    set_file = folder / "set.json"

    big = asset(set_file, "big.jpg")
    with Image.open(folder / str(big["resized"])) as image:
        assert image.size == (1536, 1024)
        assert image.format == "JPEG"
    rotated = asset(set_file, "rotated.jpg")
    assert (rotated["width"], rotated["height"]) == (600, 800)
    with Image.open(folder / str(rotated["resized"])) as image:
        assert image.size == (600, 800)
    alpha = asset(set_file, "alpha.png")
    assert str(alpha["resized"]).endswith(".png")
    with Image.open(folder / str(alpha["resized"])) as image:
        assert image.mode == "RGBA"


def test_removed_files_leave_set_and_resized_copy(tmp_path: Path) -> None:
    folder = identity_set(tmp_path, 3)
    first = scan(tmp_path).sets[0]
    gone = next(a for a in first.assets if a.file == "3.jpg")

    (folder / "3.jpg").unlink()
    second = scan(tmp_path).sets[0]

    assert [a.file for a in second.assets] == ["1.jpg", "2.jpg"]
    assert not (folder / str(gone.resized)).exists()


def test_identity_primary_defaults_and_survives_rescan(tmp_path: Path) -> None:
    folder = identity_set(tmp_path, 3)
    make_image(folder / "10.jpg", color=10)
    make_image(folder / "11.jpg", color=11)

    ref_set = scan(tmp_path).sets[0]
    assert [a.file for a in ref_set.primary_assets] == ["1.jpg", "2.jpg", "3.jpg", "10.jpg"]

    set_primary("person_01", ["11.jpg", "2.jpg"], tmp_path)
    rescanned = scan(tmp_path).sets[0]
    assert [a.file for a in rescanned.primary_assets] == ["2.jpg", "11.jpg"]


def test_set_primary_limits(tmp_path: Path) -> None:
    folder = identity_set(tmp_path, 6)
    make_image(folder / "small.jpg", (100, 100))
    make_image(tmp_path / "creative" / "ads" / "ad.jpg")
    scan(tmp_path)

    with pytest.raises(ReferenceLibraryError, match="1 to 4"):
        set_primary("person_01", ["1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg"], tmp_path)
    with pytest.raises(ReferenceLibraryError, match="identity sets only"):
        set_primary("creative/ads", ["ad.jpg"], tmp_path)
    with pytest.raises(ReferenceLibraryError, match="Not in"):
        set_primary("person_01", ["nope.jpg"], tmp_path)
    with pytest.raises(ReferenceLibraryError, match="Rejected"):
        set_primary("person_01", ["small.jpg"], tmp_path)
    with pytest.raises(ReferenceLibraryError, match="not found"):
        load_set("person_99", tmp_path)


def test_select_identity_refs_orders_primary_first_and_caps(tmp_path: Path) -> None:
    identity_set(tmp_path, 6)
    scan(tmp_path)
    set_primary("identity/person_01", ["5.jpg", "3.jpg"], tmp_path)

    refs = select_identity_refs("person_01", 4, tmp_path)
    ref_set = load_set("person_01", tmp_path)
    by_id = {a.asset_id: a.file for a in ref_set.assets}

    assert [by_id[r.asset_id] for r in refs] == ["3.jpg", "5.jpg", "1.jpg", "2.jpg"]
    assert all(r.path.is_file() and r.path.parent.name == "_resized" for r in refs)
    assert len(select_identity_refs("person_01", 2, tmp_path)) == 2


def test_assets_by_type_and_list_sets(tmp_path: Path) -> None:
    identity_set(tmp_path, 2)
    make_image(tmp_path / "product" / "mug" / "mug.jpg")
    scan(tmp_path)

    grouped = assets_by_type(tmp_path)

    assert len(grouped["identity"]) == 2
    assert len(grouped["product"]) == 1
    assert grouped["brand"] == [] and grouped["creative"] == []
    assert [s.set_id for s in list_sets("product", tmp_path)] == ["product/mug"]


def test_refs_cli_scan_list_and_primary(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = isolated / "refs"
    identity_set(root, 5)
    monkeypatch.setenv("REFERENCES_DIR", str(root))
    runner = CliRunner()

    scanned = runner.invoke(app, ["refs", "scan"])
    listed = runner.invoke(app, ["refs", "list"])
    chosen = runner.invoke(app, ["refs", "primary", "--set", "person_01", "--files", "4.jpg,5.jpg"])
    too_many = runner.invoke(
        app, ["refs", "primary", "--set", "person_01", "--files", "1.jpg,2.jpg,3.jpg,4.jpg,5.jpg"]
    )

    assert scanned.exit_code == 0
    assert "identity/person_01: 5 ok, 0 rejected, 4 primary" in scanned.output
    assert listed.exit_code == 0 and "identity/person_01" in listed.output
    assert chosen.exit_code == 0 and "4.jpg, 5.jpg" in chosen.output
    assert too_many.exit_code == 1
