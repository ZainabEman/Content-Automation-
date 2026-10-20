"""Phase 4 end-to-end check: PRD §10 acceptance criteria 1-5 and 7-9, offline
(6, the animated carousel, was removed 2026-10-16).

Run:  uv run python scripts/e2e_phase4.py [--keep]

Everything happens in a new temp folder (copies of config/, brand/ and the Jost fonts,
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
TOPICS = ["AI chatbots for dentists", "Missed calls cost clinics patients without automation",
          "Chatbots that book physiotherapy slots"]
# v5: German copy (PRD R1); the e2e also proves the German quality pass accepts it.
TAKEAWAYS = [
    "Der Chatbot beantwortet WhatsApp-Fragen zu Öffnungszeiten innerhalb von Sekunden, Tag "
    "und Nacht.",
    "Nach 18:00 Uhr bietet er per SMS die nächsten zwei freien Termine aus dem Praxiskalender "
    "an.",
    "Am Vorabend des Besuchs schickt er dem Patienten eine Erinnerung per E-Mail.",
    "Das Empfangsteam sieht morgens jeden Chat im CRM und ruft nur die offenen Fälle zurück, "
    "statt den ganzen Vormittag am Telefon zu verbringen.",
    "Neue Patienten erhalten per WhatsApp eine Begrüßung mit Adresse und Parkhinweisen.",
]
INSIGHTS = [
    "Ein Praxis-Chatbot beantwortet WhatsApp-Fragen zu Öffnungszeiten rund um die Uhr.",
    "Nach Praxisschluss bietet der Bot die nächsten zwei freien Termine aus dem Kalender an.",
    "Patienten bestätigen einen Termin im selben Chat mit seiner Nummer.",
    "Der Bot verschickt am Vorabend des Termins eine Erinnerung per E-Mail.",
    "Das Empfangsteam prüft morgens die Chats der Nacht im CRM.",
    "Nur Fälle, die der Bot im Chat nicht klären konnte, bekommen einen Rückruf am Telefon.",
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

    for name in ("config", "brand"):
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
    # Phase D: the design directions draw only the official logo (checked by hash); the sandbox
    # registers its stand-in as that file.
    import hashlib

    for variant in brand.get("logoVariants", []):
        if variant.get("file"):
            path = refs / variant["file"]
            path.parent.mkdir(parents=True, exist_ok=True)
            logo.save(path)
            variant["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (work / "config" / "brand.json").write_text(json.dumps(brand, indent=2), encoding="utf-8")
    jobs = json.loads((work / "config" / "jobs.json").read_text(encoding="utf-8"))
    jobs["free_providers"] = [p for p in jobs["free_providers"] if p != "mock"]
    (work / "config" / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    # Phase 4 uploads after generation; Phase 7 waits for the review (requireReview: true).
    (work / "config" / "storage.json").write_text(
        json.dumps({"upload": {"requireReview": False}}), encoding="utf-8")
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


COPY_LINES = ["Beantwortet Fragen nach Praxisschluss", "Bietet freie Termine per SMS an",
              "Übergibt offene Fälle an den Empfang", "Erinnert am Vortag per E-Mail"]


def _copy_value(name: str, value: Any) -> Any:
    """A filled value for one placeholder of a post format's copy (lists keep their length)."""
    if isinstance(value, list):
        return COPY_LINES[:len(value)]
    if name == "illustration":
        return "a tidy reception desk with a plant and a closed notebook in soft daylight"
    if name in ("source", "attribution", "sourceName"):
        return "Branded Genius"
    return "Ihr Chatbot bucht Termine, während Sie schlafen"


ILLUSTRATION = "a tidy reception desk with a plant and a closed notebook in soft daylight"


def _direction_copy(direction: str, template: dict[str, Any]) -> dict[str, Any]:
    """Phase D: the sample copy of config/design_preview_copy.json for this layout's fields."""
    samples = json.loads((REPO / "config" / "design_preview_copy.json").read_text(
        encoding="utf-8"))
    wanted = set(template) - {"illustration"}
    for key, sample in samples.items():
        if key.startswith(f"{direction}/") and wanted <= set(sample):
            filled = {name: sample[name] for name in wanted}
            if "illustration" in template:
                filled["illustration"] = ILLUSTRATION
            return filled
    raise KeyError(f"no sample copy for {direction} with {sorted(wanted)}")


def _fill_brief(template: Path) -> None:
    data: dict[str, Any] = json.loads(template.read_text(encoding="utf-8"))
    brief = {key: value for key, value in data.items() if key != "_help"}
    ids = brief["sourceArticleIds"]
    brief.update({
        "service": "AI chatbots",
        "objective": "Praxen zeigen, wie ein Chatbot nach Feierabend Termine bucht",
        "keyPoints": ["Beantwortet WhatsApp-Fragen nachts", "Bucht freie Termine per SMS",
                      "Übergibt offene Fälle an den Empfang"],
        "insights": [{"text": text, "source": ids[i % len(ids)]}
                     for i, text in enumerate(INSIGHTS)],
        "cta": ("Fordern Sie Ihre kostenfreie KI-Potenzialanalyse an: Wir zeigen Ihnen, wie "
                "ein Praxis-Chatbot Ihre Patienten per WhatsApp berät, Termine bucht und "
                "rechtzeitig vor dem Besuch erinnert."),
        "hashtags": ["#BrandedGenius", "#Healthcare", "#Chatbots"],
    })
    brief["post"].update({
        "format": "statement", "audienceLine": "FÜR PRAXEN",
        "headline": "Ihr Chatbot bucht Termine, während Sie schlafen", "highlight": ["Chatbot"],
        "subheadline": "Der Bot bietet nach 18:00 Uhr freie Termine per WhatsApp an",
        "points": ["Beantwortet WhatsApp-Fragen nachts", "Bietet nach 18:00 Uhr Termine per SMS",
                   "Erinnert Patienten per E-Mail"],
    })
    if brief.get("platform") == "linkedin":  # only a LinkedIn post may leave the man out
        brief["post"]["person"] = False
    for key in ("stat", "source", "sourceName"):
        brief["post"].pop(key, None)
    if brief["post"].get("direction"):  # Phase D: the direction's layout fields
        brief["post"]["altText"] = ("Grafik mit der Überschrift über einen Praxis-Chatbot, "
                                    "daneben ein Bild zum Thema")
        brief["post"]["copy"] = _direction_copy(brief["post"]["direction"], brief["post"]["copy"])
    elif isinstance(brief["post"].get("copy"), dict):  # a post format: fill only its fields
        brief["post"]["copy"] = {name: _copy_value(name, value)
                                 for name, value in brief["post"]["copy"].items()}
    caption = brief["captions"][next(iter(brief["captions"]))]
    caption.update({
        "hook": "Die meisten Patienten, die Ihrer Praxis nach 18:00 Uhr schreiben, buchen "
                "woanders, bevor sie eine Antwort bekommen.",
        "takeaways": TAKEAWAYS,
        "question": "Welche Fragen stellen Ihre Patienten nach Praxisschluss am häufigsten, "
                    "und wer beantwortet sie heute?",
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
    templates = sorted(work.glob("outputs/*/*/*/*/brief.template.json"))
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
    folders = len(list(work.glob("outputs/_system/jobs/*/*/details.json")))
    # As if the build crashed after the last image was made but before package.json was saved:
    # the last package built (a crash stops the run, so nothing later changes its design picks).
    package_file = max(work.glob("outputs/*/*/*/*/package.json"),
                       key=lambda path: max(p.stat().st_mtime for p in
                                            path.parent.glob("final/*")))
    package = json.loads(package_file.read_text(encoding="utf-8"))
    package["items"]["post"] = {"status": "pending", "picks": package["items"]["post"].get("picks")}
    package["status"] = "brief needed"
    package_file.write_text(json.dumps(package), encoding="utf-8")
    # The finished build closed its authorization (Phase 7), so the run again has its own
    # dry run and "ok"; the job is then reused (nothing is made or charged again).
    _, out, _ = _ca("content", "build", str(package_file.parent), "--dry-run")
    again = [line.split()[3] for line in out.splitlines() if line.startswith("Dry run ID:")]
    code, out, err = _ca("content", "build", str(package_file.parent),
                         *(["--authorize", again[0]] if again else []))
    conn = _db()
    reused = conn.execute("SELECT COUNT(*) FROM events WHERE type = 'job_reused'").fetchone()[0]
    conn.close()
    after = len(list(work.glob("outputs/_system/jobs/*/*/details.json")))
    _check(c, code == 0 and reused == 1 and after == folders,
           f"run again: job_reused {reused}, image folders {folders} -> {after}")
    c.notes.append(f"dry run {ids[0]}; mock counted as paid")


def c5(c: Criterion) -> None:
    from content_automation.registry import db_path, open_registry
    from content_automation.registry.auth import legacy_authorization
    from content_automation.registry.jobs import JobConfig, open_job

    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    # The build's own authorization closed when it finished (Phase 7): a small open one.
    legacy_authorization(conn, "BG-001", "mock", "usd", 0.5, "e2e: a small approved max")
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
    tracker = work / "outputs" / "_system" / "drive-mock" / "Content Automation" / "tracking.csv"
    text = tracker.read_text(encoding="utf-8")
    tracker.write_text(text.replace("AI chatbots for dentists", "Edited by the manager", 1),
                       encoding="utf-8")
    folder = next(path.parent for path in sorted(work.glob("outputs/*/*/*/*/package.json"))
                  if "dentists" in path.read_text(encoding="utf-8"))
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
