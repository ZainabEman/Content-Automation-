"""Track L Step 2: face check, `ca job review --person`, one automatic redo, ad strictness."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.content import package
from content_automation.content.deliverables import Deliverable
from content_automation.core.config import Settings
from content_automation.core.jobs import Job, JobParams, create_job
from content_automation.workflows import person_check
from content_automation.workflows.person_check import face_problems, is_group


def _job(output_dir: Path, provider: str = "higgsfield_soul") -> Job:
    job = create_job(output_dir, workflow_id="social_creative", workflow_version="1",
                     requested_by="test", request="post", prompt="@Roman, at a desk",
                     provider=provider, model="Soul 2.0",
                     params=JobParams(aspect_ratio="1:1", image_size="1K", count=1),
                     inputs={"personShown": True})
    job.start()
    image = Image.new("RGB", (640, 640), (20, 60, 160))
    ImageDraw.Draw(image).rectangle((100, 100, 400, 400), fill=(230, 230, 230))
    image.save(job.folder / "image-1.png")
    job.complete(["image-1.png"])
    return job


def test_face_check_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plain = tmp_path / "plain.png"
    Image.new("RGB", (640, 640), (20, 60, 160)).save(plain)
    assert face_problems(plain, group=False, text_boxes=[]) == [
        "0 faces found (Roman alone needs exactly 1)"]
    assert face_problems(plain, group=True, text_boxes=[]) == [
        "no face found (a group scene needs at least one)"]
    monkeypatch.setattr(person_check, "face_boxes", lambda image: [(0.4, 0.4, 0.6, 0.6)])
    assert face_problems(plain, group=False, text_boxes=[(0.0, 0.0, 1.0, 0.3)]) == []
    assert face_problems(plain, group=False, text_boxes=[(0.0, 0.3, 1.0, 0.7)]) == [
        "a face sits in the text-overlay zone"]
    assert is_group("Roman with his team", ("team",)) and not is_group("Roman alone", ("team",))


def test_job_review_person(isolated: Path) -> None:
    job = _job(isolated / "outputs")
    failed = CliRunner().invoke(app, ["job", "review", str(job.folder), "--person", "fail",
                                      "the", "hairline", "differs"])
    assert failed.exit_code == 0, failed.output
    review = Job.load(job.folder / "details.json").review("image-1.png")
    assert review is not None and (review.result, review.note) == ("fail", "the hairline differs")
    assert CliRunner().invoke(app, ["job", "review", str(job.folder), "--person",
                                    "pass"]).exit_code == 2  # a pass needs what was seen


def test_one_automatic_redo_then_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                      make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    made: list[Job] = []

    def run(workflow: str, inputs: Any, settings: Settings, cold_start: bool = True) -> Job:
        made.append(_job(settings.output_dir))
        return made[-1]

    monkeypatch.setattr(package, "run_workflow", run)
    monkeypatch.setattr(package, "check_job_image", lambda job, name, s: ["2 faces found"])
    plan = package._ImagePlan(slot=cast(Any, None), jobs=[cast(Any, None)])
    folder = tmp_path / "pkg"
    folder.mkdir()
    item, lines = package._make_images("post", plan, folder, settings, None)
    assert len(made) == 2 and item.status == "failed"  # the first + one redo
    assert item.error and "person check failed" in item.error and "a new dry run" in lines[1]
    first = made[0].review("image-1.png")
    assert first is not None and first.result == "fail"

    monkeypatch.setattr(package, "check_job_image", lambda job, name, s: [])
    item, lines = package._make_images("post", plan, folder, settings, None)
    assert item.status == "review" and any("--person pass" in line for line in lines)

    made[-1].add_review("image-1.png", "fail", "the hairline differs")  # Codex: not Roman
    count = len(made)
    item, lines = package._make_images("post", plan, folder, settings, item)
    assert len(made) == count and item.status == "failed"  # reported, never redone by itself
    assert item.error and "Codex check: the hairline differs" in item.error


def test_ads_never_take_a_fallback_provider() -> None:
    ad = Deliverable.model_validate({"kind": "ad", "label": "ad", "part": "ad",
                                     "platform": "facebook", "format": "ad",
                                     "provider": "mock", "aliases": ["ad"]})
    specs = {"facebook_ad": ad}
    assert package.ad_provider_problem(specs, "openrouter", "mock") is not None
    assert package.ad_provider_problem(specs, "mock", "mock") is None
    assert package.ad_provider_problem(specs, None, "mock") is None
