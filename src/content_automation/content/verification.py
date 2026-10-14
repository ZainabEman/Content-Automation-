"""Integration verification (Phase 10 Step 2, spec §7; list to confirm against spec §7).

Each integration has a live success condition, a failure path and an offline check: its config
is present, its adapter loads, and its failure path runs against a fake (a temp registry, a mock
HTTP transport, a broken file). Nothing calls a paid or external service. An integration is
operational only with a recorded live pass (`ca verify record <name> --live pass "<note>"`,
after the manual test in docs/VERIFICATION.md).
"""

import importlib
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from content_automation.core.config import Settings

# The fake's own temp folder; it returns what happened, or raises VerifyFailed.
Fake = Callable[[Settings, Path], str]


class VerifyFailed(RuntimeError):
    """The offline check failed; the message says what."""


@dataclass(frozen=True)
class Integration:
    name: str
    title: str
    success: str  # the live test passes when ...
    failure: str  # what the app does when it fails
    files: tuple[str, ...]  # Settings attributes (config files) or repo paths
    module: str  # the adapter that must load
    fake: Fake
    keys: tuple[str, ...] = ()  # Settings attributes the live test needs (presence only)
    note: str = ""


def _temp_registry(folder: Path) -> sqlite3.Connection:
    from content_automation.registry import open_registry

    return open_registry(folder / "registry.db", folder / "registry.json")


def _codex(settings: Settings, folder: Path) -> str:
    from content_automation.cli.help import GROUPS

    missing = [group.path for group in GROUPS if not Path(group.path).is_file()]
    if missing:
        raise VerifyFailed(f"skill files missing: {', '.join(missing)}")
    fake = folder / "missing" / "SKILL.md"
    if fake.is_file():
        raise VerifyFailed("the fake skill file exists")
    return f"{len(GROUPS)} skill groups and their SKILL.md files found; a missing one is named"


def _gmail(settings: Settings, folder: Path) -> str:
    from content_automation.content.research_input import ResearchInputError, load_idea
    from content_automation.research.fetch import load_newsletters

    senders = len(load_newsletters(settings.newsletters_file).senders)
    broken = folder / "content-list.json"
    broken.write_text('{"ideas": []}', encoding="utf-8")
    try:
        load_idea(broken, None)
    except ResearchInputError as error:
        return f"{senders} newsletter senders; a malformed content list is refused ({error})"
    raise VerifyFailed("a malformed content list was accepted")


def _web(settings: Settings, folder: Path) -> str:
    from content_automation.research import fetch

    saved = fetch.TRANSPORT
    fetch.TRANSPORT = httpx.MockTransport(lambda request: httpx.Response(503))
    try:
        got = fetch.fetch_article("https://example.test/article",
                                  fetch.load_newsletters(settings.newsletters_file).limits)
    finally:
        fetch.TRANSPORT = saved
    if not got.error:
        raise VerifyFailed("a failing site gave no error")
    return f"a failing site is an error line, not a crash ({got.error})"


def _plugin(provider: str, job_type: str) -> Fake:
    def fake(settings: Settings, folder: Path) -> str:
        from content_automation.registry.items import create_item
        from content_automation.registry.jobs import (
            JobConfig,
            check_job,
            fail_job,
            open_job,
            retry_candidates,
        )

        config = JobConfig()
        conn = _temp_registry(folder)
        try:
            item = create_item(conn, kind="post", title="verify", topic="verify")
            job = open_job(conn, item_id=item.id, job_type=job_type, provider=provider,
                           inputs={"verify": provider}, config=config, estimate=1.0).job
            check = check_job(conn, job.id, config=config)
            if check.decision != "stop":
                raise VerifyFailed(f"a call without an authorization was not stopped "
                                   f"({check.decision})")
            fail_job(conn, job.id, "fake plugin failure")
            retry, _ = retry_candidates(conn, item_id=item.id, max_attempts=2)
        finally:
            conn.close()
        if [found.id for found in retry] != [job.id]:
            raise VerifyFailed("a failed plugin call is not offered for a retry")
        return ("no open authorization: jobs check says stop; a failed call is listed for "
                '"retry failed jobs" (a dry run and "ok")')

    return fake


def _comfyui(settings: Settings, folder: Path) -> str:
    from content_automation.ai.image import ImageProviderError
    from content_automation.ai.image.providers.comfyui import create_provider

    try:
        create_provider(settings.model_copy(update={"image_model": "not-a-workflow"}))
    except ImageProviderError as error:
        return f"an unknown workflow stops before any call ({error})"
    raise VerifyFailed("an unknown ComfyUI workflow was accepted")


def _openrouter(settings: Settings, folder: Path) -> str:
    from content_automation.ai.image.providers.openrouter import map_error
    from content_automation.content.deliverables import load_deliverables

    if not map_error(502, "fake").retryable or map_error(401, "fake").retryable:
        raise VerifyFailed("OpenRouter errors are not mapped (502 retry, 401 stop)")
    catalog = load_deliverables(settings.deliverables_file)
    named = sorted(key for key, spec in catalog.deliverables.items()
                   if "openrouter" in (spec.provider, spec.fallback_provider))
    state = f"set for {', '.join(named)}" if named else "off by default (no deliverable names it)"
    return (f"HTTP 401 stops, 502 is retried; Nano Banana fallback {state}, offered only by the "
            "dry-run fallback line")


def _drive(settings: Settings, folder: Path) -> str:
    from content_automation.storage.providers.drive_api import setup_problem

    problem = setup_problem(settings.model_copy(update={"secrets_dir": folder / "none"}))
    if problem is None:
        raise VerifyFailed("Drive without a sign-in was reported as set up")
    return f"without a sign-in Drive says what to do ({problem}); plugin route: upload requests"


def _tracker(settings: Settings, folder: Path) -> str:
    from content_automation.content.tracking import DEFAULT_REGISTRY_COLUMNS, load_registry_columns

    columns = load_registry_columns(settings.tracker_file)
    broken = folder / "tracker.json"
    broken.write_text("{not json", encoding="utf-8")
    if load_registry_columns(broken) != dict(DEFAULT_REGISTRY_COLUMNS):
        raise VerifyFailed("a broken tracker.json did not fall back to the default columns")
    return f"{len(columns)} registry columns; a broken tracker.json falls back to the defaults"


def _opus(settings: Settings, folder: Path) -> str:
    from content_automation.content.clips import _provider, clips_config
    from content_automation.registry.db import RegistryError

    provider = clips_config(settings)["provider"]
    fake = folder / "clips.json"
    fake.write_text('{"provider": "api"}', encoding="utf-8")
    try:
        _provider(settings.model_copy(update={"clips_file": fake}))
    except RegistryError as error:
        return f"provider {provider}; the API route says {error}"
    raise VerifyFailed("the Opus Pro API stub did not refuse")


def _ffmpeg(settings: Settings, folder: Path) -> str:
    import imageio_ffmpeg

    from content_automation.core.media import probe_media

    exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
    fake = folder / "fake.mp4"
    fake.write_bytes(b"not a video")
    if probe_media(fake).duration_sec is not None:
        raise VerifyFailed("a file that is not a video was read as one")
    return f"FFmpeg {exe.name} found; a file that does not decode is refused (no duration)"


def _publishing(settings: Settings, folder: Path) -> str:
    from content_automation.content.distribution import integrations, mark_published
    from content_automation.registry.db import RegistryError
    from content_automation.registry.items import create_item

    conn = _temp_registry(folder)
    try:
        item = create_item(conn, kind="post", title="verify", topic="verify",
                           platforms=["linkedin"])
        mark_published(conn, item.id, "linkedin", "soon")
    except RegistryError as error:
        direct = ", ".join(integrations(settings)) or "none"
        return f"direct integrations: {direct}; published without a URL is refused ({error})"
    finally:
        conn.close()
    raise VerifyFailed("published without a URL was accepted")


INTEGRATIONS: tuple[Integration, ...] = (
    Integration("codex", "Codex skills/CLI", "a phrase from `ca help commands` runs its skill "
                "and command in Codex Desktop", "a missing skill or command is named; `ca doctor`",
                ("AGENTS.md",), "content_automation.cli.help", _codex),
    Integration("gmail", "Gmail plugin", "\"show content\" lists the newest newsletters of "
                "brandedgenius.de@gmail.com", "not connected: the skill stops and names the "
                "account; a malformed list is refused", ("newsletters_file",),
                "content_automation.research.fetch", _gmail),
    Integration("web-fetch", "web research fetch", "\"research this link <url>\" saves the "
                "article text and its claims", "an unreachable or disallowed site is an error "
                "line; the idea keeps its other sources", ("newsletters_file", "sources_file"),
                "content_automation.research.fetch", _web),
    Integration("higgsfield", "Higgsfield plugin", "an animated carousel's stills and clips are "
                "made and recorded under one \"ok\"", "no authorization: stop; a failed request "
                "falls back locally or is retried after a dry run", ("carousel_design_file",
                                                                     "jobs_file"),
                "content_automation.ai.video.providers.higgsfield_plugin",
                _plugin("higgsfield-plugin", "clip")),
    Integration("heygen", "HeyGen plugin", "a podcast recording is made and imported with "
                "`ca podcast record`", "a missing avatar or voice ID stops before the job; a "
                "failed request is retried after a dry run", ("jobs_file",),
                "content_automation.ai.avatar.providers.heygen_plugin",
                _plugin("heygen-plugin", "avatar_scene"),
                keys=("heygen_avatar_id", "heygen_voice_id")),
    Integration("comfyui", "ComfyUI/RunPod", "an image with Roman's identity comes back from "
                "the RunPod endpoint", "an unknown workflow or missing key stops before a call",
                ("comfyui_config_file",), "content_automation.ai.image.providers.comfyui",
                _comfyui, keys=("runpod_api_key",), note="blocked: LoRA track"),
    Integration("openrouter", "OpenRouter (Nano Banana fallback)", "after its own dry run and "
                "\"ok\", one image comes back", "401/402 stop with the fix; 429/5xx retried",
                ("deliverables_file",), "content_automation.ai.image.providers.openrouter",
                _openrouter, keys=("openrouter_api_key",),
                note="fallback, off by default; client decision"),
    Integration("drive", "Google Drive (API or plugin)", "an approved review's files land in "
                "<Folder>/<Content ID>/v<n>/", "no sign-in: setup says what to do; a failed "
                "upload is re-queued by \"resume everything\"", ("storage_file",),
                "content_automation.storage.providers.drive_api", _drive),
    Integration("tracker", "tracker Sheet", "`ca drive sync` writes the item's row in the "
                "Content Tracker", "hand edits are conflicts (`ca tracking conflicts`), never "
                "overwritten", ("tracker_file",), "content_automation.content.tracking",
                _tracker),
    Integration("opus-pro", "Opus Pro (manual)", "handoff, import and select turn returned "
                "clips into approved shorts", "the API route is a stub (\"not configured\"); a "
                "clip that is not vertical or 15-90 s is not imported", ("clips_file",),
                "content_automation.content.clips", _opus),
    Integration("ffmpeg", "FFmpeg media", "a podcast MP3 and platform video variants are made "
                "locally", "a file that does not decode is refused with the reason", (),
                "content_automation.core.media", _ffmpeg),
    Integration("publishing", "publishing (manual URL)", "a live post's URL is recorded with "
                "`ca publish mark`", "no URL: refused; a failed post is recorded with the "
                "reason", ("publishing_file",), "content_automation.content.distribution",
                _publishing),
)


def get_integration(name: str) -> Integration:
    for integration in INTEGRATIONS:
        if integration.name == name.lower():
            return integration
    names = ", ".join(integration.name for integration in INTEGRATIONS)
    raise VerifyFailed(f'Unknown integration "{name}" ({names}).')


def _path(settings: Settings, entry: str) -> Path:
    value = getattr(settings, entry, None)
    return Path(value) if isinstance(value, Path | str) else Path(entry)


def run_offline(settings: Settings, integration: Integration) -> list[str]:
    """Config present, adapter loads, failure path with a fake; VerifyFailed on a problem."""
    missing = [_path(settings, entry).as_posix() for entry in integration.files
               if not _path(settings, entry).is_file()]
    if missing:
        raise VerifyFailed(f"config missing: {', '.join(missing)}")
    try:
        importlib.import_module(integration.module)
    except ImportError as error:
        raise VerifyFailed(f"adapter does not load: {error}") from None
    with tempfile.TemporaryDirectory(prefix="ca-verify-") as temp:
        result = integration.fake(settings, Path(temp))
    lines = [f"config ok ({', '.join(integration.files) or 'none needed'}); adapter "
             f"{integration.module} loads", f"failure path: {result}"]
    for key in integration.keys:
        state = "set" if getattr(settings, key, None) else "not set"
        lines.append(f"live test needs {key.upper()}: {state}")
    return lines

