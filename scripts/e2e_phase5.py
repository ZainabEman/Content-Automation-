"""Phase 5 end-to-end check: PRD §7 acceptance criteria 1-9, offline.

Run:  uv run python scripts/e2e_phase5.py [--keep]

A new temp folder with copies of config/ and brand/; mock scraper and storage, link
fetching through httpx's MockTransport (no network, no paid call). Main flow: newsletter list ->
ideas with sources -> manual topic -> scores and claims -> approvals -> month plan -> generate.
Prints PASS or FAIL per criterion; exit code 0 only when all pass. --keep leaves the folder.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MONTH, WEEK = "2026-11", "2026-W45"
PAGE = "<html><body><article>" + "".join(
    f"<p>Part {n}: fraudsters clone the voices of managers to order urgent transfers.</p>"
    for n in range(8)) + "</article></body></html>"
TODAY = datetime.now(UTC).date()


@contextmanager
def _sandbox(keep: bool) -> Iterator[Path]:
    work = Path(tempfile.mkdtemp(prefix="e2e-phase5-"))
    old_cwd, old_env = Path.cwd(), dict(os.environ)
    try:
        os.chdir(work)
        for name in ("config", "brand"):
            shutil.copytree(REPO / name, work / name)
        for name in list(os.environ):
            if name.isupper() and name.endswith(("_PROVIDER", "_MODEL", "_FILE", "_DIR")):
                del os.environ[name]
        os.environ.update({"SCRAPER_PROVIDER": "mock", "STORAGE_PROVIDER": "mock",
                           "IMAGE_PROVIDER": "mock", "OUTPUT_DIR": str(work / "outputs")})
        yield work
    finally:
        os.chdir(old_cwd)
        os.environ.clear()
        os.environ.update(old_env)
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def _mock_links() -> None:
    import httpx

    from content_automation.research import fetch

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "link.marketingaiinstitute.com":
            return httpx.Response(302, headers={"location": "https://www.golem.de/voice-clones"})
        return httpx.Response(200, html=PAGE)

    fetch.TRANSPORT = httpx.MockTransport(handler)


def _ca(*args: str) -> tuple[int, str]:
    from typer.testing import CliRunner

    from content_automation.cli import app

    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.output


def _db() -> sqlite3.Connection:
    from content_automation.registry import db_path, open_registry

    return open_registry(db_path(Path("state")), Path("config/registry.json"))


def _content_list() -> Path:
    day = TODAY.isoformat()
    ideas = [
        {"number": 1, "title": "AI voice clones target German Mittelstand finance teams",
         "summary": "Deepfake calls ask for urgent transfers.", "sources": [
             {"title": "Voice clone fraud", "source": "Marketing AI Institute",
              "url": "https://link.marketingaiinstitute.com/c/123", "date": day,
              "excerpt": "Fraudsters clone a manager's voice."}]},
        {"number": 2, "title": "AI voice clones target German Mittelstand finance team",
         "summary": "The same story from another newsletter.", "sources": [
             {"title": "Voice clones", "source": "The Neuron", "url": None, "date": day,
              "excerpt": "Finance teams get deepfake calls."}]},
        {"number": 3, "title": "Ten Instagram caption templates",
         "summary": "Templates for captions.", "sources": [
             {"title": "Captions", "source": "Unknown Weekly", "url": None, "date": day,
              "excerpt": "Caption ideas."}]},
    ]
    path = Path("research/newsletters") / f"{day}_content-list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": day, "ideas": ideas}), encoding="utf-8")
    return path


def c1_c2_c5(notes: dict[int, list[str]]) -> None:
    from content_automation.registry.ideas import get_details
    from content_automation.registry.sources import item_sources

    code, out = _ca("research", "run", "--newsletters", "--list", str(_content_list()))
    notes[1].append("ok" if code == 0 and "collected 3" in out else f"failed: {out[-200:]}")
    conn = _db()
    try:
        sources = item_sources(conn, "BG-001")
        golem = [s for s in sources if s.original_url == "https://www.golem.de/voice-clones"]
        notes[1].append("original URL kept" if golem and golem[0].purpose
                        else "failed: no original URL/purpose")
        notes[2].append("merged, 2 sources" if len(sources) == 2 and "duplicates 1" in out
                        else f"failed: {len(sources)} sources")
        flags = get_details(conn, "BG-002").flags
        notes[5].append("off_strategy kept" if "off_strategy" in flags else "failed: no flag")
    finally:
        conn.close()


def c3(notes: list[str]) -> None:
    from content_automation.registry.sources import add_source

    conn = _db()
    try:
        old = (TODAY - timedelta(days=400)).isoformat()
        heise, golem, taz = (add_source(
            conn, "article", url=f"https://news.example/{n}", publisher=publisher,
            published_at=day, trust="secondary")[0].id
            for n, publisher, day in ((1, "heise", TODAY.isoformat()),
                                      (2, "golem", TODAY.isoformat()), (3, "taz", old)))
    finally:
        conn.close()
    claim = ("claims", "add", "BG-001", "--text", "Deepfake calls rose", "--label", "fact")
    one = _ca(*claim, "--source", heise)[1]
    two = _ca(*claim, "--source", heise, "--source", golem)[1]
    stale = _ca(*claim, "--source", taz)[1]
    forced = _ca(*claim, "--source", heise, "--status", "verified")[0]
    ok = ("unverified" in one and ": verified" in two and "outdated" in stale and forced == 2)
    notes.append("rules hold, no --status" if ok else f"failed: {one} {two} {stale} {forced}")


def c4(notes: list[str]) -> None:
    from content_automation.registry.ideas import get_details, list_ideas

    text = "Why do German clinics trust AI triage?? (note from a call)"
    code, _ = _ca("ideas", "add", text, "--assume", "audience: clinic owners")
    again = _ca("ideas", "add", text)[1]
    scored = _ca("ideas", "score", "BG-003", "--pillar", "german_problems", "--relevance", "4",
                 "--german", "yes", "--reason", "German clinics")[1]
    conn = _db()
    try:
        details = [d for i, d in list_ideas(conn) if d.original_text == text]
        ok = (code == 0 and len(details) == 1 and "duplicate" in again
              and get_details(conn, "BG-003").score is not None and "score" in scored)
    finally:
        conn.close()
    notes.append("verbatim, deduped, scored" if ok else "failed: manual topic")


def c6_c7_c8(notes: dict[int, list[str]]) -> None:
    from content_automation.registry.approvals import approve
    from content_automation.registry.decisions import list_decisions
    from content_automation.registry.ideas import create_idea, update_details
    from content_automation.registry.items import children, list_items
    from content_automation.registry.strategy import load_strategy

    pillars = load_strategy(Path("config/strategy.json")).pillars
    spread = [p.key for p in pillars for _ in range(round(p.target_share * 20))]
    conn = _db()
    try:
        for n in range(48):  # the user approves ideas (here directly in the registry)
            idea = create_idea(conn, f"Backlog idea {n} on {spread[n % len(spread)]}")
            update_details(conn, idea.id, pillar=spread[n % len(spread)], score=80 - n)
            approve(conn, idea.id, gate="idea", note="e2e: the user's approval")
    finally:
        conn.close()
    # v5/v6: the plan fills the four categories only (no short, podcast or YouTube rows; YouTube
    # is planned by `ca plan month`, scripts/e2e_v5.py) and names the slots left empty.
    code, out = _ca("calendar", "plan", "--month", MONTH)
    conn = _db()
    try:
        planned = [i for i in list_items(conn) if i.parent_id and i.planned_date]
        kinds = {i.deliverable for i in planned}
        notes[6].append(f"{len(planned)} rows, {len(kinds)} categories"
                        if code == 0 and planned and kinds <= CATEGORIES
                        else f"failed: {sorted(map(str, kinds))} {out[:300]}")
        parent = planned[0].parent_id if planned else None
        rows = children(conn, parent) if parent else []
        decision = list_decisions(conn, rows[0].id)[0] if rows else None
        notes[7].append("child items, inherited approval" if rows and decision
                        and decision.actor == "system" and "inherited" in (decision.text or "")
                        else "failed: no children or inheritance")
    finally:
        conn.close()
    code, out = _ca("calendar", "generate", "--week", WEEK)
    notes[8].append("drafts with a dry-run next step" if code == 0 and "--dry-run" in out
                    else f"failed: {out[-300:]}")


def c9(notes: list[str]) -> None:
    from content_automation.research.models import load_sources

    # The live fix d5d9607 enabled the German sources (before v5); v5 (PRD R9.3) wants them,
    # so the check is that they are present (enabled or not).
    german = [s for s in load_sources(Path("config/sources.json")) if s.language == "de"]
    enabled = sum(1 for s in german if s.runs)
    notes.append(f"{len(german)} present, {enabled} enabled" if german
                 else "failed: German sources")


CATEGORIES = {"instagram_carousel", "facebook_post", "facebook_ad", "linkedin_post"}
CRITERIA = {
    1: "newsletter list -> ideas with sources, purposes, original URLs, run counts",
    2: "a duplicate from another source is merged; sources kept",
    3: "claim rules: 1 secondary unverified, 2 publishers verified, old outdated, no --status",
    4: "a manual topic is kept verbatim and goes through dedupe and scoring",
    5: "an off-strategy idea is flagged, not dropped",
    6: "calendar plan --month fills only the four v5 categories (no short/podcast/YouTube rows)",
    7: "planned rows are child items with inherited approval in the log",
    8: "calendar generate makes drafts and points to a --dry-run build (nothing paid)",
    9: "German candidate sources are present (enabled since the live fix d5d9607; v5 R9.3)",
}


def run(keep: bool = False) -> dict[int, list[str]]:
    sys.path.insert(0, str(REPO / "src"))
    notes: dict[int, list[str]] = {number: [] for number in CRITERIA}
    with _sandbox(keep) as work:
        _mock_links()
        steps: list[tuple[list[int], Callable[[], None]]] = [
            ([1, 2, 5], lambda: c1_c2_c5(notes)), ([3], lambda: c3(notes[3])),
            ([4], lambda: c4(notes[4])), ([6, 7, 8], lambda: c6_c7_c8(notes)),
            ([9], lambda: c9(notes[9])),
        ]
        for numbers, step in steps:
            try:
                step()
            except Exception as error:  # a crash fails its criteria; the run goes on
                for number in numbers:
                    notes[number].append(f"error: {type(error).__name__}: {error}")
        if keep:
            print(f"Kept: {work}")
    return notes


def main() -> int:
    notes = run(keep="--keep" in sys.argv)
    passed = 0
    for number, text in CRITERIA.items():
        ok = bool(notes[number]) and not any(
            note.startswith(("failed", "error")) for note in notes[number])
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'} {number}: {text} ({'; '.join(notes[number])})")
    print(f"{passed}/{len(CRITERIA)} criteria passed (criterion 10, the checks, is ruff + mypy "
          "+ pytest).")
    return 0 if passed == len(CRITERIA) else 1


if __name__ == "__main__":
    raise SystemExit(main())
