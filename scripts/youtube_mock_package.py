"""One complete YouTube topic package from local fixtures (PRD v5 R9, §7.11-7.12), offline.

Run:  uv run python scripts/youtube_mock_package.py [--keep]

A temp folder with a copy of config/ and a fresh registry; the source pages are the fixture HTML
files in tests/fixtures/youtube/ served by an httpx.MockTransport (no internet). The flow:
plan → approve → research template → research (fixture) → check-sources (a dead URL and a
missing quotation fail first) → scripts → three teleprompter files (fixtures) → bilingual →
English filled (fixture) → check → select style B → storyboard. The finished topic folder is
copied to outputs/previews/youtube/ for Roman's review of the formats. The topic is a MOCK:
its sources are invented test pages on example.org.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "youtube"
PREVIEW = REPO / "outputs" / "previews" / "youtube"
PAGES = {"https://example.org/artikel-1": "artikel-1.html",
         "https://example.org/artikel-2": "artikel-2.html"}
TITLE = "Deepfake-Anrufe im Namen der Geschäftsführung"


def transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        name = PAGES.get(str(request.url).rstrip("/"))
        if name is None:
            return httpx.Response(404, text="<html><title>Not found</title></html>")
        return httpx.Response(200, text=(FIXTURES / name).read_text(encoding="utf-8"),
                              headers={"content-type": "text/html; charset=utf-8"})

    return httpx.MockTransport(handler)


@contextmanager
def sandbox(keep: bool = False) -> Iterator[Path]:
    work = Path(tempfile.mkdtemp(prefix="youtube-mock-"))
    shutil.copytree(REPO / "config", work / "config")
    old = Path.cwd()
    saved = {name: os.environ.pop(name) for name in list(os.environ)
             if name.isupper() and name.endswith(("_PROVIDER", "_MODEL", "_FILE", "_DIR"))}
    os.chdir(work)
    try:
        yield work
    finally:
        os.chdir(old)
        os.environ.update(saved)
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def run(copy_to: Path | None = PREVIEW, keep: bool = False) -> dict[str, Any]:
    from typer.testing import CliRunner

    from content_automation.cli import app
    from content_automation.youtube import sources
    from content_automation.youtube.topic import load_config

    load_config.cache_clear()
    sources.TRANSPORT = transport()
    runner = CliRunner()
    result: dict[str, Any] = {"steps": {}}

    def ca(*args: str) -> tuple[int, str]:
        done = runner.invoke(app, list(args))
        return done.exit_code, done.output

    try:
        with sandbox(keep) as work:
            code, out = ca("youtube", "plan", "2026-11", "--topic", TITLE)
            bg_id = next(line.split()[0] for line in out.splitlines() if line.startswith("BG-"))
            result["bgId"] = bg_id
            result["steps"]["plan"] = code
            result["steps"]["approve"] = ca("item", "approve", bg_id)[0]
            result["steps"]["template"] = ca("youtube", "research", bg_id)[0]
            folder = next((work / "outputs" / "youtube" / "2026-11").glob(f"{bg_id}_*"))
            research = next(folder.glob("research_*.txt"))
            filled = (FIXTURES / "research.txt").read_text(encoding="utf-8")
            broken = filled.replace("https://example.org/artikel-2",
                                    "https://example.org/gibt-es-nicht").replace(
                "Die Stimme klang genau wie", "Die Stimme klang fast wie")
            research.write_text(broken.replace("{BG_ID}", bg_id), encoding="utf-8")
            code, out = ca("youtube", "check-sources", bg_id)
            result["failedCheck"] = {"code": code, "output": out}
            result["steps"]["blocked"] = ca("youtube", "scripts", bg_id)[0]
            research.write_text(filled.replace("{BG_ID}", bg_id), encoding="utf-8")
            code, out = ca("youtube", "check-sources", bg_id)
            result["steps"]["check-sources"] = code
            result["passedCheck"] = out
            result["steps"]["scripts"] = ca("youtube", "scripts", bg_id)[0]
            english = json.loads((FIXTURES / "english.json").read_text(encoding="utf-8"))
            folders = {"A": "style-A_investigativ", "B": "style-B_direkte-warnung",
                       "C": "style-C_menschlich"}
            for key, name in folders.items():
                shutil.copy(FIXTURES / f"teleprompter_{key}.txt",
                            folder / name / "teleprompter_DE.txt")
            result["steps"]["bilingual"] = ca("youtube", "bilingual", bg_id)[0]
            for key, name in folders.items():
                path = folder / name / "script_DE-EN.txt"
                text = path.read_text(encoding="utf-8")
                for translation in english[key]:
                    text = text.replace("<English translation of the German paragraph above>",
                                        translation, 1)
                path.write_text(text, encoding="utf-8")
            code, out = ca("youtube", "check", bg_id)
            result["steps"]["check"] = code
            result["checkOutput"] = out
            code, out = ca("youtube", "select-style", bg_id, "B")
            result["steps"]["select"] = code
            os.environ["STORAGE_PROVIDER"] = "mock"  # outputs/drive/, fake links, no Google
            code, out = ca("youtube", "upload", bg_id)
            os.environ.pop("STORAGE_PROVIDER", None)
            result["steps"]["upload"] = code
            result["uploadOutput"] = out
            drive = work / "outputs" / "drive" / "Content Automation"
            result["driveFiles"] = sorted(path.relative_to(drive).as_posix()
                                          for path in drive.rglob("*") if path.is_file())
            tracker = drive / "tracking.csv"
            result["tracker"] = tracker.read_text(encoding="utf-8") if tracker.is_file() else ""
            result["files"] = sorted(path.relative_to(folder).as_posix()
                                     for path in folder.rglob("*") if path.is_file())
            result["folderName"] = folder.name
            if copy_to is not None:
                target = copy_to / folder.name
                shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(folder, target)
                (copy_to / "README.txt").write_text(
                    "MOCK YouTube topic package (PRD v5 R9.11), made offline by "
                    "scripts/youtube_mock_package.py from tests/fixtures/youtube/. The sources "
                    "are invented test pages on example.org; the texts show the formats only.\n",
                    encoding="utf-8")
                result["copiedTo"] = target.as_posix()
    finally:
        sources.TRANSPORT = None
        load_config.cache_clear()
    return result


def main() -> int:
    result = run(keep="--keep" in sys.argv)
    for name, code in result["steps"].items():
        print(f"{name}: exit {code}")
    print(f"Files: {', '.join(result.get('files', []))}")
    print(f"Copied to: {result.get('copiedTo')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
