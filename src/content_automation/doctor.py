"""`ca doctor`: check that everything needed is in place, with a plain-English fix for each
problem. Key values are never shown, only whether they are set."""

import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
import imageio_ffmpeg
from pydantic import SecretStr

from content_automation.core.config import ConfigurationError, Settings, load_settings
from content_automation.media.assemble import text_support
from content_automation.references import (
    BrandProfileError,
    list_sets,
    load_brand,
    load_company,
)
from content_automation.research.collectors import USER_AGENT
from content_automation.research.models import SourcesError, load_sources

Level = Literal["ok", "warn", "fail"]
SETUP_GUIDE = "docs/SETUP-CODEX.md"


@dataclass(frozen=True)
class Check:
    level: Level
    name: str
    detail: str
    fix: str = ""


def run_checks(env_file: Path = Path(".env")) -> list[Check]:
    checks = [_python(), _uv()]
    if not env_file.is_file():
        checks.append(Check("fail", ".env file", "not found",
                            f"Copy .env.example to .env (see {SETUP_GUIDE})."))
    else:
        checks.append(Check("ok", ".env file", "found"))
    try:
        settings = load_settings(require_credentials=False, create_directories=False)
    except ConfigurationError as error:
        checks.append(Check("fail", "Settings", str(error), "Fix the named lines in .env."))
        return checks
    checks += _keys(settings)
    checks += _providers(settings)
    checks += _ffmpeg()
    checks += _references(settings)
    checks += _brand_and_company(settings)
    checks += _sources(settings)
    checks += _folders(settings)
    return checks


def _python() -> Check:
    version = sys.version_info
    text = f"{version.major}.{version.minor}.{version.micro}"
    if (version.major, version.minor) == (3, 13):
        return Check("ok", "Python", text)
    return Check("fail", "Python", text, "Run `uv sync` in this folder; uv installs Python 3.13.")


def _uv() -> Check:
    path = shutil.which("uv")
    if path:
        return Check("ok", "uv", "installed")
    return Check("fail", "uv", "not found",
                 "Install uv (https://docs.astral.sh/uv/getting-started/installation/), "
                 "then open a new terminal.")


def _is_set(secret: SecretStr | None) -> bool:
    return secret is not None and bool(secret.get_secret_value().strip())


def _keys(settings: Settings) -> list[Check]:
    checks = []
    openrouter = _is_set(settings.openrouter_api_key)
    if settings.image_provider == "openrouter" and not openrouter:
        checks.append(Check("fail", "OPENROUTER_API_KEY", "set: no",
                            "Add your OpenRouter key to .env (OPENROUTER_API_KEY=...)."))
    else:
        checks.append(Check("ok", "OPENROUTER_API_KEY", f"set: {'yes' if openrouter else 'no'}"))
    if settings.voice_provider == "elevenlabs":
        elevenlabs = _is_set(settings.elevenlabs_api_key)
        checks.append(Check("ok" if elevenlabs else "fail", "ELEVENLABS_API_KEY",
                            f"set: {'yes' if elevenlabs else 'no'}",
                            "" if elevenlabs else "Add ELEVENLABS_API_KEY to .env, or set "
                            "VOICE_PROVIDER=none."))
    return checks


def _providers(settings: Settings) -> list[Check]:
    checks = []
    if settings.image_provider == "mock":
        checks.append(Check("warn", "Images", "mock (free placeholder pictures)",
                            "For real images set IMAGE_PROVIDER=openrouter in .env."))
    else:
        checks.append(Check("ok", "Images", f"{settings.image_provider} ({settings.image_model})"))
    for label, provider, real in (
        ("Video", settings.video_provider, "higgsfield-mcp"),
        ("Avatar", settings.avatar_provider, "heygen-mcp"),
    ):
        if provider in ("mock", "none"):
            detail = "mock (placeholder clips)" if provider == "mock" else "none (not set)"
            checks.append(Check("warn", label,
                                f"{detail}; content packages keep their video pending",
                                f"After connecting the MCP in Codex, set "
                                f"{label.upper()}_PROVIDER={real} in .env "
                                "(docs/guides/module-2-video.md)."))
        else:
            checks.append(Check("ok", label,
                                f"{provider}: Codex must have this MCP connected and signed in"))
    if settings.avatar_provider == "heygen-mcp" and not settings.heygen_avatar_id:
        checks.append(Check("warn", "HEYGEN_AVATAR_ID", "not set",
                            "Ask Codex to list your HeyGen avatars, then put the ID in .env."))
    voice = "off (no voiceover in the MVP)" if settings.voice_provider == "none" else (
        settings.voice_provider)
    checks.append(Check("ok", "Voice", voice))
    if settings.scraper_provider == "mock":
        checks.append(Check("warn", "News scraper", "mock (made-up articles)",
                            "For real news set SCRAPER_PROVIDER=free in .env."))
    else:
        checks.append(Check("ok", "News scraper", settings.scraper_provider))
    return checks


def _ffmpeg() -> list[Check]:
    try:
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run([exe, "-version"], capture_output=True, timeout=30, check=True)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return [Check("fail", "FFmpeg", "not working", "Run `uv sync` again (it installs FFmpeg).")]
    font, note = text_support()
    text = Check("ok", "Video text", note) if font else Check(
        "warn", "Video text", note, "Videos still work; captions.srt carries the text.")
    return [Check("ok", "FFmpeg", "found"), text]


def _references(settings: Settings) -> list[Check]:
    scan_fix = "Put the photos in assets/reference/... and run `uv run ca refs scan`."
    sets = list_sets(None, settings.references_dir)
    if not sets:
        return [Check("fail", "Reference photos", "no scanned sets", scan_fix)]
    checks = []
    identity = [s for s in sets if s.type == "identity" and s.ok_assets]
    if identity:
        names = ", ".join(f"{s.set_id} ({len(s.ok_assets)} photos)" for s in identity)
        checks.append(Check("ok", "Person photos", names))
    else:
        checks.append(Check("fail", "Person photos", "no identity set with usable photos",
                            "Add photos to assets/reference/identity/person_01/ and run "
                            "`uv run ca refs scan`."))
    if any(s.set_id == "brand/logo" and s.ok_assets for s in sets):
        checks.append(Check("ok", "Logo", "brand/logo"))
    else:
        checks.append(Check("warn", "Logo", "no usable logo",
                            "Add a PNG/JPG logo to assets/reference/brand/logo/ and rescan."))
    if any(s.type == "creative" and s.ok_assets for s in sets):
        checks.append(Check("ok", "Style examples", "creative sets found"))
    else:
        checks.append(Check("warn", "Style examples", "none",
                            "Add past ads to assets/reference/creative/facebook_ads/ and rescan."))
    return checks


def _brand_and_company(settings: Settings) -> list[Check]:
    checks = []
    try:
        brand = load_brand(settings.references_dir)
        checks.append(Check("ok", "brand.json", f"{brand.brand_name} ({brand.status})"))
    except BrandProfileError as error:
        checks.append(Check("fail", "brand.json", str(error),
                            "Restore assets/reference/brand/brand.json (see the Module 1 guide)."))
    company = load_company(settings.company_file)
    if company is None:
        checks.append(Check("fail", "services.md", f"{settings.company_file} not found",
                            "Restore docs/company/services.md (company profile)."))
    else:
        checks.append(Check("ok", "services.md", f"{len(company.services)} services"))
    return checks


def _sources(settings: Settings) -> list[Check]:
    try:
        sources = [s for s in load_sources(settings.sources_file) if s.active]
    except SourcesError as error:
        return [Check("fail", "News sources", str(error).splitlines()[0],
                      f"Fix {settings.sources_file} (see the Module 3 guide).")]
    checks = []
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, timeout=10, follow_redirects=True) as client:
        for source in sources:
            url = source.rss_url or source.url
            try:
                status = client.get(url).status_code
            except httpx.HTTPError as error:
                checks.append(Check("fail", f"Source: {source.name}", type(error).__name__,
                                    "Check the internet connection (and Codex network access), "
                                    "or pause this site in config/sources.json."))
                continue
            if status < 400:
                checks.append(Check("ok", f"Source: {source.name}", f"reachable (HTTP {status})"))
            else:
                checks.append(Check("fail", f"Source: {source.name}", f"HTTP {status}",
                                    "The site blocks us or is down; pause it in "
                                    "config/sources.json (\"active\": false)."))
    return checks


def _folders(settings: Settings) -> list[Check]:
    checks = []
    for name, folder in (
        ("OUTPUT_DIR", settings.output_dir),
        ("PACKAGES_DIR", settings.packages_dir),
        ("RESEARCH_DIR", settings.research_dir),
    ):
        probe = folder / f".write-test-{uuid.uuid4().hex[:8]}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as error:
            checks.append(Check("fail", name, f"{folder}: not writable ({type(error).__name__})",
                                f"Check the folder permissions or change {name} in .env."))
            continue
        checks.append(Check("ok", name, f"{folder} (writable)"))
    return checks
