"""Phase 4 end-to-end check: PRD §10 acceptance criteria 1-9, offline.

Run:  uv run python scripts/e2e_phase4.py [--keep]

Everything happens in a new temp folder (copies of config/, docs/company/ and the Jost fonts,
a small fake reference library); mock providers only, no network, no paid call. The mock image
provider is counted as paid here (config/jobs.json in the temp folder), so the dry run ->
"ok" -> --authorize path runs as it would for a real provider. Prints PASS or FAIL per
criterion; the exit code is 0 only when every criterion passes. --keep leaves the temp folder.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
WEEK = "2026-W45"
FAKE_KEY = "sk-or-v1-e2efakefakefake0123456789abcdef"
TOPICS = ["AI chatbots for dentists", "Missed calls cost clinics patients",
          "Chatbots that book physiotherapy slots"]
TAKEAWAYS = [
    "The chatbot answers WhatsApp questions about opening hours within seconds, day and night.",
    "After 18:00 it offers the next two free slots from the practice calendar by SMS.",
    "It sends the patient a reminder by email the evening before the visit.",
    "Reception sees every chat in the CRM the next morning and calls back only open cases.",
    "New patients get a WhatsApp welcome message with the address and parking tips.",
]
INSIGHTS = [
    "A practice chatbot answers WhatsApp questions about opening hours at any time.",
    "After closing time the bot offers the next two free slots from the calendar.",
    "Patients confirm a slot by replying with its number in the same chat.",
    "The bot sends an email reminder the evening before the appointment.",
    "Reception reviews the night's chats in the CRM each morning.",
    "Only cases the bot could not settle get a call back from the team.",
]


@dataclass
class Criterion:
    number: int
    text: str
    passed: bool = False
    notes: list[str] = field(default_factory=list)

    def line(self) -> str:
        detail = f" ({'; '.join(self.notes)})" if self.notes else ""
        return f"{'PASS' if self.passed else 'FAIL'} {self.number}: {self.text}{detail}"


@contextmanager
def _sandbox(keep: bool) -> Iterator[Path]:
    """A temp working folder and environment; both restored afterwards."""
    work = Path(tempfile.mkdtemp(prefix="e2e-phase4-"))
    old_cwd, old_env = Path.cwd(), dict(os.environ)
    try:
        os.chdir(work)
        yield work
    finally:
        os.chdir(old_cwd)
        os.environ.clear()
        os.environ.update(old_env)
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def _setup(work: Path) -> None:
    from PIL import Image

    for name in ("config", "docs/company"):
        shutil.copytree(REPO / name, work / name)
    fonts = work / "assets" / "fonts"
    fonts.mkdir(parents=True)
    for font in (REPO / "assets" / "fonts").glob("Jost-*.ttf"):
        shutil.copy(font, fonts / font.name)
    refs = work / "refs"
    for i in range(1, 7):
        path = refs / "identity" / "person_01" / f"{i}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (600, 800), (i * 41 % 256, i * 97 % 256, 150)).save(path)
    for i in range(1, 13):
        path = refs / "creative" / "facebook_ads_masked" / f"ad{i:02d}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (600, 800), (i * 13 % 256, 60, i * 29 % 256)).save(path)
    logo = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    logo.paste((20, 80, 200, 255), (40, 110, 260, 190))
    (refs / "brand" / "logo").mkdir(parents=True)
    brand = json.loads((work / "config" / "brand.json").read_text(encoding="utf-8"))
    names = {str(brand.get("logoFile") or "logo.png"), "logo.png", "logo (1).png"}
    for name in names:
        logo.save(refs / "brand" / "logo" / name)
    jobs = json.loads((work / "config" / "jobs.json").read_text(encoding="utf-8"))
    jobs["free_providers"] = [p for p in jobs["free_providers"] if p != "mock"]
    (work / "config" / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    design_path = work / "config" / "carousel_design.json"
    design = json.loads(design_path.read_text(encoding="utf-8"))
    design["stills"]["referenceImages"] = "no"  # no style frames in the temp folder
    design_path.write_text(json.dumps(design), encoding="utf-8")
    for name in list(os.environ):
        if name.isupper() and name.endswith(("_PROVIDER", "_MODEL", "_FILE", "_DIR")):
            del os.environ[name]
    os.environ.update({
        "REFERENCES_DIR": str(refs), "IMAGE_PROVIDER": "mock", "SCRAPER_PROVIDER": "mock",
        "STORAGE_PROVIDER": "mock", "VIDEO_PROVIDER": "mock", "AVATAR_PROVIDER": "mock",
        "VOICE_PROVIDER": "mock",
    })
    from content_automation.references import list_sets, scan, tag_assets

    scan(refs)
    style = [a.asset_id for s in list_sets("creative", refs) for a in s.ok_assets]
    tag_assets(style, people=False, logo=False, root=refs)


def _ca(*args: str) -> tuple[int, str, str]:
    from typer.testing import CliRunner

    from content_automation.cli import app

    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.stdout, result.stderr


def _fill_brief(template: Path) -> None:
    data: dict[str, Any] = json.loads(template.read_text(encoding="utf-8"))
    brief = {key: value for key, value in data.items() if key != "_help"}
    ids = brief["sourceArticleIds"]
    brief.update({
        "service": "AI Chatbots & AI Development",
        "objective": "Show practices how a chatbot books appointments after hours",
        "keyPoints": ["Answers WhatsApp questions at night", "Books free slots by SMS",
                      "Hands open cases to reception"],
        "insights": [{"text": text, "source": ids[i % len(ids)]}
                     for i, text in enumerate(INSIGHTS)],
        "cta": ("Book a free consultation call and we show you how a practice chatbot answers, "
                "books and reminds your patients on WhatsApp."),
        "hashtags": ["#BrandedGenius", "#Healthcare", "#Chatbots"],
    })
    brief["post"].update({
        "format": "statement", "audienceLine": "FOR PRACTICES",
        "headline": "Your chatbot books patients while you sleep", "highlight": ["chatbot"],
        "subheadline": "The bot offers free slots by WhatsApp after 18:00",
        "points": ["Answers WhatsApp questions at night", "Offers free slots by SMS after 18:00",
                   "Reminds patients by email"],
        "person": False,
    })
    for key in ("stat", "source", "sourceName"):
        brief["post"].pop(key, None)
    caption = brief["captions"][next(iter(brief["captions"]))]
    caption.update({
        "hook": "Most patients who message your practice after 18:00 never hear back before "
                "they book somewhere else.",
        "takeaways": TAKEAWAYS,
        "question": "Which questions do your patients ask most often after closing time, and "
                    "who answers them today?",
    })
    (template.parent / "brief.json").write_text(json.dumps(brief, indent=2), encoding="utf-8")


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect("state/registry.db")
    conn.row_factory = sqlite3.Row
    return conn


def _check(criterion: Criterion, condition: bool, note: str) -> None:
    if not condition:
        criterion.notes.append(f"failed: {note}")


def c1(c: Criterion) -> None:
    args = ["calendar", "new", "--week", WEEK]
    for topic in TOPICS:
        args += ["--topic", topic]
    code, out, err = _ca(*args)
    _check(c, code == 0, f"calendar new exit {code}: {err.strip()}")
    _check(c, "Items: row 1 BG-001, row 2 BG-002, row 3 BG-003" in out, "BG IDs per row")
    code, out, _ = _ca("item", "status", "BG-001")
    _check(c, code == 0 and all(f"{dim} " in out for dim in
                                ("idea", "generation", "review", "upload", "publication")),
           "status shows the five statuses")
    c.notes.append("3 rows: BG-001..BG-003")


def c2(c: Criterion) -> None:
    code, out, _ = _ca("calendar", "approve", "1", "--week", WEEK)
    _check(c, code == 0 and "BG-001 idea: proposed → approved (v1)" in out, "approve by row")
    code, out, _ = _ca("item", "reject", "BG-002", "too", "generic")
    _check(c, code == 0 and 'reason: "too generic"' in out, "reject with reason")
    code, _, err = _ca("item", "reject", "BG-002")
    _check(c, code == 2 and "needs a reason" in err, "reject without a reason refused")
    code, _, err = _ca("item", "approve", "BG-002", "--gate", "review")
    _check(c, code == 1 and "review gate is not open" in err and len(err.splitlines()) == 1,
           "illegal move refused with one clear line")
    conn = _db()
    text = conn.execute("SELECT text FROM decisions WHERE item_id = 'BG-002' AND action = "
                        "'reject'").fetchone()
    _check(c, text is not None and text["text"] == "too generic", "reason stored")
    conn.close()


def c3(c: Criterion) -> None:
    code, out, _ = _ca("item", "revise", "BG-003", "focus", "on", "Mittelstand", "--title",
                       "Chatbots that book physiotherapy slots in the Mittelstand")
    _check(c, code == 0 and "v2 created" in out, "revise creates v2")
    conn = _db()
    rows = conn.execute("SELECT version, status, feedback FROM versions WHERE item_id = "
                        "'BG-003' ORDER BY version").fetchall()
    idea = conn.execute("SELECT idea_status FROM items WHERE id = 'BG-003'").fetchone()[0]
    conn.close()
    _check(c, [(r["version"], r["status"]) for r in rows] == [(1, "active"), (2, "pending")],
           "v1 remains, v2 pending")
    _check(c, idea == "proposed", "needs approval again")
    code, out, _ = _ca("item", "approve", "BG-003")
    _check(c, "BG-003 idea: proposed → approved (v2)" in out, "approved again on v2")


def c4(c: Criterion, work: Path) -> None:
    code, out, err = _ca("calendar", "generate", "--week", WEEK)
    _check(c, code == 0, f"stage 1 exit {code}: {err.strip()[:200]}")
    templates = sorted(work.glob("outputs/content/*/brief.template.json"))
    _check(c, len(templates) == 2, f"{len(templates)} packages started (2 approved rows)")
    for template in templates:
        _fill_brief(template)
    code, out, err = _ca("calendar", "generate", "--week", WEEK)
    ids = [line.split()[3] for line in out.splitlines() if line.startswith("Dry run ID:")]
    _check(c, code == 0 and len(ids) == 1, f"combined dry run with its ID ({err.strip()[:200]})")
    if not ids:
        return
    code, _, err = _ca("calendar", "generate", "--week", WEEK, "--build")
    _check(c, code == 1 and "Not authorized" in err, "build without --authorize refused")
    code, out, err = _ca("calendar", "generate", "--week", WEEK, "--build", "--authorize",
                         ids[0])
    _check(c, code == 0 and out.count("Row is Generated.") == 2,
           f"both rows built ({err.strip()[:200]})")
    conn = _db()
    auths = conn.execute("SELECT dryrun_id, provider, status FROM authorizations").fetchall()
    images = conn.execute("SELECT COUNT(*) FROM jobs WHERE job_type = 'image' AND status = "
                          "'succeeded'").fetchone()[0]
    conn.close()
    _check(c, [(a["dryrun_id"], a["provider"]) for a in auths] == [(ids[0], "mock")],
           "one authorization for the dry run")
    _check(c, images == 2, f"{images} image jobs succeeded")
    folders = len(list(work.glob("outputs/jobs/*/*/details.json")))
    # As if the build crashed after the last image was made but before package.json was saved:
    # the last package built (a crash stops the run, so nothing later changes its design picks).
    package_file = max(work.glob("outputs/content/*/package.json"),
                       key=lambda path: max(p.stat().st_mtime for p in
                                            path.parent.glob("images/*")))
    package = json.loads(package_file.read_text(encoding="utf-8"))
    package["items"]["post"] = {"status": "pending", "picks": package["items"]["post"].get("picks")}
    package["status"] = "brief needed"
    package_file.write_text(json.dumps(package), encoding="utf-8")
    code, out, err = _ca("content", "build", str(package_file.parent))
    conn = _db()
    reused = conn.execute("SELECT COUNT(*) FROM events WHERE type = 'job_reused'").fetchone()[0]
    conn.close()
    after = len(list(work.glob("outputs/jobs/*/*/details.json")))
    _check(c, code == 0 and reused == 1 and after == folders,
           f"run again: job_reused {reused}, image folders {folders} -> {after}")
    c.notes.append(f"dry run {ids[0]}; mock counted as paid")


def c5(c: Criterion) -> None:
    from content_automation.registry import db_path, open_registry
    from content_automation.registry.jobs import JobConfig, open_job

    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    opened = open_job(conn, item_id="BG-001", job_type="image", provider="mock",
                      inputs={"e2e": "over budget"}, config=JobConfig(free_providers=()),
                      estimate=1.0)
    conn.close()
    code, out, _ = _ca("jobs", "check", str(opened.job.id))
    _check(c, out.splitlines()[:1] == ["stop"] and "not started" in out, "check says stop")
    db = _db()
    status = db.execute("SELECT status FROM jobs WHERE id = ?", (opened.job.id,)).fetchone()[0]
    exceeded = db.execute("SELECT COUNT(*) FROM events WHERE type = 'authorization_exceeded'"
                          ).fetchone()[0]
    db.close()
    _check(c, status == "queued" and exceeded >= 1, f"job {status}, exceeded logged {exceeded}")
    code, out, _ = _ca("jobs", "cancel", str(opened.job.id), "over", "budget", "(e2e)")
    _check(c, code == 0 and "cancelled" in out, "the user cancels it")


def c6(c: Criterion, work: Path) -> None:
    from content_automation.registry import db_path, open_registry
    from content_automation.registry.approvals import approve
    from content_automation.registry.auth import create_from_dry_run
    from content_automation.registry.dryruns import CostLine, save_dry_run
    from content_automation.registry.items import create_item
    from content_automation.registry.jobs import JobConfig
    from content_automation.registry.runtime import Scope, activate
    from content_automation.workflows.carousel_design import SlideText, load_carousel_design
    from content_automation.workflows.carousel_plugin import (
        load_request,
        output_file,
        planned_split,
        write_still_requests,
    )
    from content_automation.workflows.carousel_render import background

    design = load_carousel_design(Path("config/carousel_design.json"))
    types = ("cover", "point", "stat", "point", "list", "point", "point", "final")
    slides = [SlideText(type=kind, headline=f"Slide {n}", body="Text")  # type: ignore[arg-type]
              for n, kind in enumerate(types, start=1)]
    package = Path("outputs/content/2026-10-13_e2e-carousel")
    package.mkdir(parents=True)
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    item = create_item(conn, kind="carousel", title="WhatsApp flows", topic="WhatsApp flows",
                       platforms=["instagram"], deliverable="instagram_carousel",
                       package_path=package.as_posix())
    approve(conn, item.id, gate="idea")
    split = planned_split(package, slides, design)
    assert split is not None
    lines = [CostLine(item.id, "still", "higgsfield-plugin", "credits", split[0], split[1]),
             CostLine(item.id, "clip", "higgsfield-plugin", "credits", split[2], split[3])]
    dry = save_dry_run(Path("state"), "e2e carousel", [item.id], lines, expiry_hours=24)
    create_from_dry_run(conn, dry, free=())
    with activate(Scope(conn, JobConfig(), command="e2e",
                        part_of={"instagram_carousel": "carousel"})):
        write_still_requests(package, "WhatsApp flows", slides, design)
    conn.close()

    def make(slide: int) -> None:
        job = load_request(package, "still", slide).job_id
        code, out, _ = _ca("jobs", "check", str(job))
        _check(c, out.splitlines()[:1] == ["go"], f"check still {slide}")
        target = output_file(package, "still", slide)
        target.parent.mkdir(parents=True, exist_ok=True)
        background(design).save(target)
        code, _, err = _ca("carousel", "record", str(package), "--still", str(slide),
                           "--credits", "5")
        _check(c, code == 0, f"record still {slide}: {err.strip()[:120]}")

    for slide in (1, 2, 3):
        make(slide)
    code, out, _ = _ca("jobs", "list", "--unfinished")
    _check(c, "4 job(s)" in out, "4 unfinished still jobs listed")
    code, out, _ = _ca("jobs", "resume", item.id)
    _check(c, code == 0 and "still_04" in out and "still_07" in out, "resume names the next")
    for slide in (4, 5, 6, 7):
        make(slide)
    code, out, _ = _ca("jobs", "list", "--unfinished")
    _check(c, out.strip() == "No jobs match.", "nothing unfinished after the resume")
    code, out, _ = _ca("jobs", "resume")
    _check(c, out.strip() == "No unfinished jobs.", "resume: nothing left")


def c7(c: Criterion) -> None:
    os.environ["OPENROUTER_API_KEY"] = FAKE_KEY
    _ca("item", "history", f"BG-001 {FAKE_KEY}")  # the key in a command line
    code, out, _ = _ca("audit", "show", "--limit", "2000", "--json")
    events = json.loads(out) if code == 0 else []
    kinds = {event["type"] for event in events}
    wanted = {"command_run", "decision", "authorization_created", "job_succeeded",
              "upload_succeeded", "status_changed", "version_created", "tracker_synced"}
    _check(c, wanted <= kinds, f"missing {sorted(wanted - kinds)}")
    raw = Path("state/registry.db").read_bytes()
    _check(c, FAKE_KEY not in out and FAKE_KEY.encode() not in raw, "fake key redacted")
    c.notes.append(f"{len(events)} events, {len(kinds)} types")


def c8(c: Criterion, work: Path) -> None:
    path = work / "calendar" / f"{WEEK}.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("Missed calls", "Lost calls"),
                    encoding="utf-8")
    code, _, err = _ca("calendar", "approve", "2", "--week", WEEK)
    _check(c, code == 2 and "edited by hand" in err and "+2,BG-002" in err,
           "calendar write stopped with a diff")
    code, out, _ = _ca("calendar", "sync", "--week", WEEK, "--discard-edits")
    _check(c, code == 0 and "Missed calls" in path.read_text(encoding="utf-8"),
           "edits discarded on request")
    tracker = work / "outputs" / "drive" / "Content Automation" / "tracking.csv"
    text = tracker.read_text(encoding="utf-8")
    tracker.write_text(text.replace("AI chatbots for dentists", "Edited by the manager", 1),
                       encoding="utf-8")
    folder = sorted(work.glob("outputs/content/*/package.json"))[0].parent
    code, out, _ = _ca("drive", "sync", str(folder))
    _check(c, "not written (conflicts" in out, "tracker row with a hand edit not written")
    code, out, _ = _ca("tracking", "conflicts")
    _check(c, "hand edit" in out and "Edited by the manager" in out, "conflict report")
    _check(c, "Edited by the manager" in tracker.read_text(encoding="utf-8"),
           "the hand edit stays")


def c9(c: Criterion, work: Path) -> None:
    migration = work / "migration"
    migration.mkdir()
    fixtures = REPO / "tests" / "fixtures" / "migration"
    for name in ("calendar", "outputs"):
        shutil.copytree(fixtures / name, migration / name)
    shutil.copytree(work / "config", migration / "config")
    os.chdir(migration)
    os.environ["SECRETS_DIR"] = str(fixtures / "secrets-fake")
    try:
        code, first, _ = _ca("registry", "migrate")
        code2, second, _ = _ca("registry", "migrate")
    finally:
        os.chdir(work)
        del os.environ["SECRETS_DIR"]
    _check(c, code == 0 and first.startswith("7 created"), f"first run: {first[:60]}")
    _check(c, code2 == 0 and second.startswith("0 created, 7 skipped"),
           f"second run: {second[:60]}")


STEPS: list[tuple[int, str, Callable[..., None], bool]] = [
    (1, "a calendar gives each row a BG ID; status shows the five statuses", c1, False),
    (2, "approve/reject/revise by ID, reasons stored, illegal moves refused", c2, False),
    (3, "revise creates v2; approval again; v1 remains", c3, False),
    (4, "generate approved: one authorization + jobs; running again reuses jobs", c4, True),
    (5, "a job over its authorization is not started", c5, False),
    (6, "an interrupted carousel is listed as unfinished and finished by resume", c6, True),
    (7, "the audit log lists commands, decisions, authorizations, jobs, uploads; no secret",
     c7, False),
    (8, "hand-edited calendar CSV and tracker cell are not overwritten", c8, True),
    (9, "the migration is idempotent", c9, True),
]


def run(keep: bool = False) -> list[Criterion]:
    sys.path.insert(0, str(REPO / "src"))
    results: list[Criterion] = []
    with _sandbox(keep) as work:
        _setup(work)
        for number, text, step, needs_work in STEPS:
            criterion = Criterion(number, text)
            try:
                step(criterion, work) if needs_work else step(criterion)
            except Exception as error:  # a crash fails the criterion, the run goes on
                criterion.notes.append(f"error: {type(error).__name__}: {error}")
            criterion.passed = not any(note.startswith(("failed", "error"))
                                       for note in criterion.notes)
            results.append(criterion)
        if keep:
            print(f"Kept: {work}")
    return results


def main() -> int:
    results = run(keep="--keep" in sys.argv)
    for criterion in results:
        print(criterion.line())
    passed = sum(criterion.passed for criterion in results)
    print(f"{passed}/{len(results)} criteria passed (criterion 10, the checks, is ruff + mypy "
          "+ pytest).")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
