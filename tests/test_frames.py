import subprocess
from pathlib import Path

import imageio_ffmpeg
import pytest

from content_automation.references import extract_frames, load_set, scan, select_set_refs


def make_video(path: Path, pattern: str = "testsrc", seconds: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"{pattern}=duration={seconds}:size=640x640:rate=10",
            "-pix_fmt", "yuv420p", "-y", str(path),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return path


@pytest.fixture
def carousel(tmp_path: Path) -> Path:
    folder = tmp_path / "creative" / "carousels" / "c1"
    make_video(folder / "slide a.mp4")
    make_video(folder / "slide b.mp4", "testsrc2")
    return folder


def test_extract_frames_writes_three_frames_and_skips_done(tmp_path: Path, carousel: Path) -> None:
    first = extract_frames(tmp_path)
    second = extract_frames(tmp_path)

    frames = sorted(p.name for p in (carousel / "_frames").iterdir())
    assert frames == [f"slide {v}_{n}.jpg" for v in "ab" for n in (1, 2, 3)]
    assert len(first.extracted) == 2 and not first.failed
    assert len(second.skipped) == 2 and not second.extracted


def test_broken_video_is_reported_not_fatal(tmp_path: Path) -> None:
    broken = tmp_path / "creative" / "c2" / "broken.mp4"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"not a video")

    report = extract_frames(tmp_path)

    assert [label for label, _ in report.failed] == ["creative/c2/broken.mp4"]
    assert not (broken.parent / "_frames" / "broken_1.jpg").exists()


def test_scan_uses_frames_as_set_assets(tmp_path: Path, carousel: Path) -> None:
    extract_frames(tmp_path)

    report = scan(tmp_path)

    [ref_set] = report.sets
    assert ref_set.set_id == "creative/carousels/c1"
    assert len(ref_set.ok_assets) == 6
    assert all(a.file.startswith("_frames/") for a in ref_set.ok_assets)
    videos = [a for a in ref_set.rejected_assets if a.file.endswith(".mp4")]
    assert len(videos) == 2 and all("_frames/" in str(a.reason) for a in videos)
    assert not report.skipped


def test_style_selection_prefers_middle_frames(tmp_path: Path, carousel: Path) -> None:
    extract_frames(tmp_path)
    scan(tmp_path)
    ref_set = load_set("c1", tmp_path)
    by_id = {a.asset_id: a.file for a in ref_set.assets}

    refs = select_set_refs("c1", 3, tmp_path, ref_type="creative")

    assert [by_id[r.asset_id] for r in refs] == [
        "_frames/slide a_2.jpg", "_frames/slide b_2.jpg", "_frames/slide a_1.jpg",
    ]
