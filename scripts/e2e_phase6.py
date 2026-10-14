"""Phase 6 end-to-end check: PRD §7 acceptance criteria 1-7, offline.

Run:  uv run python scripts/e2e_phase6.py [--keep]

A new temp folder with a copy of config/; the registry gets an idea with sourced claims, a
YouTube item, a podcast item and a LinkedIn post. Main flow: template -> save v1 -> refusals ->
revise -> v2 -> briefs. Criterion 7 (post and carousel builds on mock, old packages) runs
scripts/e2e_phase4.py, which builds them on mock providers. No network, no paid call.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
TODAY = datetime.now(UTC).date()
LENGTHS = {"hook": 80, "german_problem": 300, "ai_risk_or_mistake": 350, "why_it_happens": 300,
           "correct_ai_solution": 400, "cta_outro": 70}


@contextmanager
def _sandbox(keep: bool) -> Iterator[Path]:
    work = Path(tempfile.mkdtemp(prefix="e2e-phase6-"))
    old_cwd, old_env = Path.cwd(), dict(os.environ)
    try:
        os.chdir(work)
        shutil.copytree(REPO / "config", work / "config")
        for name in list(os.environ):
            if name.isupper() and name.endswith(("_PROVIDER", "_MODEL", "_FILE", "_DIR")):
                del os.environ[name]
        os.environ["OUTPUT_DIR"] = str(work / "outputs")
        yield work
    finally:
        os.chdir(old_cwd)
        os.environ.clear()
        os.environ.update(old_env)
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def _ca(*args: str) -> tuple[int, str]:
    from typer.testing import CliRunner

    from content_automation.cli import app

    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.output


def _seed() -> dict[str, str]:
    from content_automation.registry import db_path, open_registry
    from content_automation.registry.approvals import approve
    from content_automation.registry.claims import add_claim
    from content_automation.registry.ideas import create_idea
    from content_automation.registry.items import create_item
    from content_automation.registry.sources import add_source

    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    try:
        idea = create_idea(conn, "Deepfake CEO calls")
        day, old = ((TODAY - timedelta(days=d)).isoformat() for d in (5, 400))
        src = [add_source(conn, "article", url=f"https://news.example/{n}", publisher=p,
                          published_at=w)[0].id
               for n, p, w in ((1, "heise", day), (2, "golem", day), (3, "taz", old))]
        ids = {"verified": add_claim(conn, idea.id, "Calls rose in 2025", "fact", src[:2]).id,
               "outdated": add_claim(conn, idea.id, "Calls were rare", "fact", [src[2]]).id,
               "opinion": add_claim(conn, idea.id, "It gets worse", "opinion", [src[0]]).id}
        approve(conn, idea.id, gate="idea", note="e2e: the user's approval")
        for key, kind, platform, deliverable in (
                ("video", "youtube", "youtube", "youtube_longform"),
                ("podcast", "podcast", "podcast", "podcast_episode"),
                ("post", "post", "linkedin", "linkedin_post"),
                ("carousel", "carousel", "instagram", "instagram_carousel"),
                ("ad", "ad", "facebook", "facebook_ad")):
            ids[key] = create_item(conn, kind=kind, title=f"Deepfake calls {key}", topic="t",
                                   platforms=[platform], parent_id=idea.id,
                                   deliverable=deliverable).id
        return ids
    finally:
        conn.close()


def _draft(item: str, version: int, verified: str, **changes: Any) -> Path:
    sections = [{"key": key, "text": " ".join(["Firms"] * count)
                 + (" In 2025 calls rose." if key == "ai_risk_or_mistake" else ""),
                 "claimRefs": [verified] if key == "ai_risk_or_mistake" else []}
                for key, count in LENGTHS.items()]
    data: dict[str, Any] = {"item": item, "version": version, "formula": "youtube_longform",
                            "language": "en", "sections": sections}
    data.update(changes)
    path = Path(f"draft-{item}-v{version}.json")
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def flow(notes: dict[int, list[str]], ids: dict[str, str]) -> None:
    from content_automation.registry import db_path, open_registry
    from content_automation.registry.versions import revise

    video = ids["video"]
    templates = [json.loads(_ca("script", "template", ids[key], "--json")[1])
                 for key in ("video", "podcast", "post", "carousel", "ad")]
    formulas = {t["formula"] for t in templates}
    claims_ok = all(len(t["claims"]) == 3 for t in templates)
    notes[1].append(f"{len(formulas)} formulas with claims" if len(formulas) == 5 and claims_ok
                    else f"failed: {formulas}")
    code, out = _ca("script", "save", video, str(_draft(video, 1, ids["verified"])))
    v1 = Path("outputs/items") / video / "scripts" / "v1"
    notes[2].append("v1, md, 10 min" if code == 0 and "about 10 min" in out
                    and (v1 / "script.md").is_file() else f"failed: {out[-200:]}")
    bad = json.loads(_draft(video, 1, ids["verified"]).read_text("utf-8"))
    bad["sections"] = bad["sections"][:-1]
    bad["sections"][0]["text"] += " 40 percent"
    bad["sections"][1]["claimRefs"] = [ids["outdated"]]
    bad["sections"][3]["claimRefs"] = [ids["opinion"]]
    Path("bad.json").write_text(json.dumps(bad), encoding="utf-8")
    code, out = _ca("script", "save", video, "bad.json")
    wanted = ("missing or empty", "number without verified source", "is outdated",
              "is opinion and unverified")
    missing = [w for w in wanted if w not in out]
    notes[3].append("4 clear refusals" if code == 1 and not missing else f"failed: {missing}")
    before = (v1 / "script.json").read_bytes()
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    try:
        revise(conn, video, "More on the Mittelstand")
    finally:
        conn.close()
    feedback = json.loads(_ca("script", "template", video, "--json")[1])["feedback"]
    code, out = _ca("script", "save", video, str(_draft(video, 2, ids["verified"])))
    notes[4].append("v2 saved, v1 unchanged, feedback shown" if code == 0 and "Saved v2" in out
                    and (v1 / "script.json").read_bytes() == before and feedback
                    else f"failed: {out[-200:]}")
    for key, fill in (("video", _youtube_brief), ("podcast", _podcast_brief)):
        skeleton = json.loads(_ca("brief", "template", ids[key], "--json")[1])["skeleton"]
        Path(f"brief-{key}.json").write_text(json.dumps(fill(skeleton)), encoding="utf-8")
        code, out = _ca("brief", "save", ids[key], f"brief-{key}.json")
        shown = _ca("brief", "show", ids[key])[1]
        notes[5].append(f"{key} brief saved and rendered" if code == 0 and "# Production brief"
                        in shown else f"failed: {key}: {out[-200:]}")
    post = {"item": ids["post"], "version": 1, "formula": "social_graphic", "language": "en",
            "hashtags": ["#BrandedGenius", "#AI", "#Leads"], "sections": [
                {"key": k, "text": v} for k, v in {
                    "central_message": "Answer every call", "audience": "Finance teams",
                    "purpose": "educational", "headline": "Your CEO never called",
                    "copy": "Your CEO never called.\n" + " ".join(["word"] * 95),
                    "visual_direction": "Roman at a desk holding a phone",
                    "cta": "Book a free analysis"}.items()]}
    Path("post.json").write_text(json.dumps(post), encoding="utf-8")
    code, out = _ca("script", "save", ids["post"], "post.json")
    notes[6].append("99 words refused" if code == 1 and "allowed 120-250" in out
                    else f"failed: {out[-200:]}")


def _youtube_brief(skeleton: dict[str, Any]) -> dict[str, Any]:
    skeleton["bRoll"][0]["description"] = "Screen recording of a fake CEO call"
    skeleton["captions"]["style"] = "burned-in"
    skeleton["thumbnail"] = {"concept": "Roman with a phone", "text": "Your CEO never called"}
    for chapter in skeleton["chapters"]:
        chapter["title"] = chapter["section"].replace("_", " ")
    skeleton.update({"musicMood": "calm, tense"})
    skeleton["presenter"]["setting"] = "Office desk, evening light"
    return skeleton


def _podcast_brief(skeleton: dict[str, Any]) -> dict[str, Any]:
    for segment in skeleton["segments"]:
        segment.update({"title": segment["section"], "minutes": 3})
    skeleton.update({"showNotes": "Sources in the description", "episodeTitle": "Voice clones",
                     "episodeDescription": "Why finance teams get fake calls"})
    return skeleton


def c7(notes: list[str]) -> None:
    result = subprocess.run([sys.executable, str(REPO / "scripts" / "e2e_phase4.py")],
                            capture_output=True, text=True, encoding="utf-8", timeout=900,
                            cwd=REPO, check=False)
    last = (result.stdout.strip().splitlines() or ["no output"])[-1]
    notes.append(f"e2e_phase4: {last}" if result.returncode == 0 else f"failed: {last}")


CRITERIA = {
    1: "templates exist for every formula and include the claims and the feedback",
    2: "a valid YouTube script saves as v1 with md and a duration estimate",
    3: "missing section, number without verified source, outdated, unacknowledged unverified fail",
    4: "a revise then a new save creates v2; v1 is unchanged",
    5: "podcast and YouTube briefs validate and render",
    6: "LinkedIn copy outside 120-250 words fails",
    7: "existing post and carousel builds still work on mock; old packages render",
}


def run(keep: bool = False) -> dict[int, list[str]]:
    sys.path.insert(0, str(REPO / "src"))
    notes: dict[int, list[str]] = {number: [] for number in CRITERIA}
    with _sandbox(keep) as work:
        steps: list[tuple[list[int], Callable[[], None]]] = [
            ([1, 2, 3, 4, 5, 6], lambda: flow(notes, _seed())),
        ]
        for numbers, step in steps:
            try:
                step()
            except Exception as error:  # a crash fails its criteria; the run goes on
                for number in numbers:
                    notes[number].append(f"error: {type(error).__name__}: {error}")
        if keep:
            print(f"Kept: {work}")
    try:
        c7(notes[7])
    except Exception as error:
        notes[7].append(f"error: {type(error).__name__}: {error}")
    return notes


def main() -> int:
    notes = run(keep="--keep" in sys.argv)
    passed = 0
    for number, text in CRITERIA.items():
        ok = bool(notes[number]) and not any(
            note.startswith(("failed", "error")) for note in notes[number])
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'} {number}: {text} ({'; '.join(notes[number])})")
    print(f"{passed}/{len(CRITERIA)} criteria passed (criterion 8, the checks, is ruff + mypy "
          "+ pytest).")
    return 0 if passed == len(CRITERIA) else 1


if __name__ == "__main__":
    raise SystemExit(main())
