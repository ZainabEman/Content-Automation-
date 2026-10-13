"""`ca doctor`: check that everything needed is in place, with a plain-English fix for each
problem. Key values are never shown, only whether they are set."""

import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import httpx
import imageio_ffmpeg
from pydantic import SecretStr

from content_automation.ai.image import (
    ImageError,
    is_unset,
    load_comfyui_config,
    load_comfyui_workflow,
)
from content_automation.content.deliverables import DeliverableError, load_deliverables
from content_automation.core.config import ConfigurationError, Settings, load_settings
from content_automation.core.limits import images_generated_on
from content_automation.media.assemble import text_support
from content_automation.references import (
    BrandProfileError,
    ReferenceLibraryError,
    ReferenceSet,
    brand_path,
    list_sets,
    load_brand,
    load_company,
    select_logo_ref,
    untagged_style_refs,
)
from content_automation.references.tracked import load_tracked, tracked_for
from content_automation.research.collectors import USER_AGENT
from content_automation.research.models import SourcesError, load_sources
from content_automation.storage import drive_setup_problem
from content_automation.workflows.design_system import DesignSystemError, load_design_system
from content_automation.workflows.logo import LogoError, load_logo

Level = Literal["ok", "warn", "fail"]
SETUP_GUIDE = "docs/SETUP-CODEX.md"
SKILLS_DIR = Path(".agents/skills")
EXPECTED_SKILLS = ("show-content", "make-content", "make-video")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


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
    checks += _comfyui(settings)
    checks.append(_drive(settings))
    checks += _skills()
    checks += _config_files(settings)
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
    comfyui = settings.image_provider == "comfyui"
    for name, is_set in (
        ("RUNPOD_API_KEY", _is_set(settings.runpod_api_key)),
        ("RUNPOD_ENDPOINT_ID", bool((settings.runpod_endpoint_id or "").strip())),
    ):
        level: Level = "fail" if comfyui and not is_set else "ok"
        fix = "Add it to .env (see docs/guides/runpod-comfyui.md)." if level == "fail" else ""
        checks.append(Check(level, name, f"set: {'yes' if is_set else 'no'}", fix))
    training = [
        name for name, value in (
            ("RUNPOD_NETWORK_VOLUME_ID", (settings.runpod_network_volume_id or "").strip()),
            ("RUNPOD_S3_ACCESS_KEY", _is_set(settings.runpod_s3_access_key)),
            ("RUNPOD_S3_SECRET_KEY", _is_set(settings.runpod_s3_secret_key)),
        ) if not value
    ]
    if training:
        checks.append(Check("warn", "LoRA training (ca lora train-remote)",
                            f"not set: {', '.join(training)}",
                            "See docs/guides/runpod-comfyui.md, section 8."))
    else:
        checks.append(Check("ok", "LoRA training (ca lora train-remote)",
                            "network volume and S3 key set"))
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
    used = images_generated_on(settings.output_dir, date.today())
    checks.append(Check("ok", "Image daily limit",
                        f"{settings.image_daily_limit} per day ({used} used today)"))
    for label, provider, real, plugin in (
        ("Video", settings.video_provider, "higgsfield-plugin", "Higgsfield"),
        ("Avatar", settings.avatar_provider, "heygen-plugin", "HeyGen"),
    ):
        if provider in ("mock", "none"):
            detail = "mock (placeholder clips)" if provider == "mock" else "none (not set)"
            checks.append(Check("warn", label,
                                f"{detail}; content packages keep their video pending",
                                f"With the {plugin} plugin installed in Codex, set "
                                f"{label.upper()}_PROVIDER={real} in .env "
                                "(docs/guides/module-2-video.md)."))
        else:
            checks.append(Check("ok", label,
                                f"{provider}: Codex makes the clips with the {plugin} plugin "
                                "(checked by Codex when a video is made)"))
    if settings.avatar_provider == "heygen-plugin":
        for name, value, what in (
            ("HEYGEN_AVATAR_ID", settings.heygen_avatar_id, "avatars"),
            ("HEYGEN_VOICE_ID", settings.heygen_voice_id, "voices (own or cloned first)"),
        ):
            if not value:
                checks.append(Check("warn", name, "not set; HeyGen clips cannot start",
                                    f"Codex lists your HeyGen {what} with the HeyGen plugin; "
                                    f"after you choose: uv run ca env set {name} <id>"))
    voice = "off (no voiceover in the MVP)" if settings.voice_provider == "none" else (
        settings.voice_provider)
    checks.append(Check("ok", "Voice", voice))
    if settings.scraper_provider == "mock":
        checks.append(Check("warn", "News scraper", "mock (made-up articles)",
                            "For real news set SCRAPER_PROVIDER=free in .env."))
    else:
        checks.append(Check("ok", "News scraper", settings.scraper_provider))
    return checks


def _comfyui(settings: Settings) -> list[Check]:
    """config/comfyui.json and both workflows; with IMAGE_PROVIDER=comfyui also the model and
    the person's LoRA (a placeholder until Phase 2 Step 4)."""
    active = settings.image_provider == "comfyui"
    guide = "See docs/guides/runpod-comfyui.md."
    try:
        config = load_comfyui_config(settings.comfyui_config_file)
        for name in config.workflows:
            load_comfyui_workflow(config, name)
    except ImageError as error:
        return [Check("fail" if active else "warn", "ComfyUI config", str(error), guide)]
    checks = [Check("ok", "ComfyUI config", f"valid: {', '.join(config.workflows)}")]
    if not active:
        return checks
    spec = config.workflows.get(settings.image_model)
    if spec is None:
        checks.append(Check("fail", "ComfyUI model", f"IMAGE_MODEL={settings.image_model}",
                            f"Set IMAGE_MODEL to one of: {', '.join(config.workflows)}."))
    elif is_unset(spec.lora_name) or is_unset(config.trigger_word):
        checks.append(Check("warn", "ComfyUI LoRA", "not set yet: images with the person are "
                            "refused before any call",
                            "Set loraName and triggerWord in config/comfyui.json (Step 4)."))
    else:
        checks.append(Check("ok", "ComfyUI LoRA", f"{spec.lora_name} ({settings.image_model})"))
    return checks


def _drive(settings: Settings) -> Check:
    """Local files only (client JSON, token, folder and tracker IDs); Google is not called."""
    setup = ("Enable the Google Drive API and the Google Sheets API in Google Cloud, save the "
             f"OAuth Desktop client JSON as {settings.secrets_dir}/google_oauth_client.json, "
             "run uv run ca drive setup (docs/SETUP-CODEX.md section 9)")
    if settings.storage_provider == "mock":
        return Check("warn", "Drive", f"mock: files and tracking.csv in "
                     f"{settings.drive_mock_dir} (fake links)", f"For Google Drive: {setup}, "
                     "then set STORAGE_PROVIDER=drive in .env.")
    problem = drive_setup_problem(settings)
    if problem:
        return Check("warn", "Drive", f"{problem}; builds stay local", f"{setup}.")
    shared = settings.drive_share_with.strip() or "nobody (private)"
    return Check("ok", "Drive", "set up: folders and Content Tracker (Drive + Sheets API); "
                 f"IDs in {settings.secrets_dir}; editors: {shared}")


def _skills() -> list[Check]:
    """Codex skills in .agents/skills: each needs a SKILL.md with a name and a description."""
    folder = SKILLS_DIR if SKILLS_DIR.is_dir() else _PROJECT_ROOT / SKILLS_DIR
    found = {}
    for path in sorted(folder.glob("*/SKILL.md")):
        match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
        fields = dict(
            line.split(":", 1) for line in (match.group(1) if match else "").splitlines()
            if ":" in line
        )
        if fields.get("name", "").strip() and fields.get("description", "").strip():
            found[path.parent.name] = fields["name"].strip()
    missing = [name for name in EXPECTED_SKILLS if name not in found]
    if missing:
        return [Check("fail", "Skills", f"missing or without name/description: "
                      f"{', '.join(missing)}", f"Restore {SKILLS_DIR}/<name>/SKILL.md from git.")]
    return [Check("ok", "Skills", f"{len(found)} found: {', '.join(sorted(found))}")]


def _config_files(settings: Settings) -> list[Check]:
    checks = []
    try:
        catalog = load_deliverables(settings.deliverables_file)
        checks.append(Check("ok", "Deliverables", f"valid: {', '.join(catalog.deliverables)}"))
    except DeliverableError as error:
        checks.append(Check("fail", "Deliverables", str(error),
                            "Restore config/deliverables.json from git."))
    try:
        system = load_design_system(settings.design_system_file)
        checks.append(Check("ok", "Design system", f"valid: {len(system.formats)} formats"))
    except DesignSystemError as error:
        checks.append(Check("fail", "Design system", str(error),
                            "Restore config/design_system.json from git."))
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
        person = next((s for s in identity if s.set_id == settings.default_identity_set), None)
        if person is None:
            checks.append(Check("fail", "DEFAULT_IDENTITY_SET",
                                f"{settings.default_identity_set} has no usable photos",
                                "Set DEFAULT_IDENTITY_SET in .env to one of the sets above."))
        elif settings.image_identity_refs_max < len(person.ok_assets):
            checks.append(Check("warn", "Identity photos per image",
                                f"{settings.image_identity_refs_max} of {len(person.ok_assets)} "
                                "are sent", f"Set IMAGE_IDENTITY_REFS_MAX="
                                f"{min(len(person.ok_assets), 13)} in .env to send all."))
        else:
            checks.append(Check("ok", "Identity photos per image",
                                f"all {len(person.ok_assets)} of {person.set_id}"))
    else:
        checks.append(Check("fail", "Person photos", "no identity set with usable photos",
                            "Add photos to assets/reference/identity/person_01/ and run "
                            "`uv run ca refs scan`."))
    checks.append(_logo(settings))
    checks.append(_tracked(settings, sets))
    if any(s.type == "creative" and s.ok_assets for s in sets):
        untagged = untagged_style_refs(settings.references_dir)
        if untagged:
            checks.append(Check("warn", "Style examples", f"{len(untagged)} not tagged yet "
                                f"(e.g. {untagged[0]}); designs with the person skip them",
                                "View each one and run: uv run ca refs tag --asset <id> "
                                "--people yes|no --logo yes|no"))
        else:
            checks.append(Check("ok", "Style examples", "creative sets found, all tagged"))
    else:
        checks.append(Check("warn", "Style examples", "none",
                            "Add past ads to assets/reference/creative/facebook_ads/ and rescan."))
    return checks


def _tracked(settings: Settings, sets: list[ReferenceSet]) -> Check:
    """Tags, primaries and masks are tracked in git; the masked copies must exist."""
    try:
        tracked = load_tracked(tracked_for(settings.references_dir))
    except ValueError as error:
        return Check("fail", "Reference settings", f"{settings.references_file}: {error}",
                     "Restore config/references.json from git.")
    if not settings.references_file.is_file():
        return Check("warn", "Reference settings", f"{settings.references_file} not found",
                     "Restore config/references.json from git (style tags, primaries, masks).")
    ids = {s.set_id for s in sets if s.ok_assets}
    missing = sorted(spec.target for spec in tracked.masks if spec.target not in ids)
    if missing:
        return Check("warn", "Masked past ads", f"not made yet: {', '.join(missing)}",
                     "Run: uv run ca refs mask")
    return Check("ok", "Reference settings",
                 f"{len(tracked.tags)} style tags, {len(tracked.masks)} masked set(s) in "
                 f"{settings.references_file}")


def _logo(settings: Settings) -> Check:
    """The app pastes the logo onto designs, so it needs a transparent background."""
    try:
        brand = load_brand(settings.references_dir)
    except BrandProfileError:
        brand = None
    try:
        ref = select_logo_ref(settings.references_dir, preferred=brand.logo_file if brand else None)
        load_logo(ref.path)
    except ReferenceLibraryError as error:
        return Check("fail", "Logo", str(error),
                     "Add the logo as a PNG with a transparent background to "
                     "assets/reference/brand/logo/, rescan, and set logoFile in brand.json.")
    except LogoError as error:
        return Check("fail", "Logo", str(error))
    return Check("ok", "Logo", f"{ref.source} (transparent; pasted by the app)")


def _brand_and_company(settings: Settings) -> list[Check]:
    checks = []
    try:
        brand = load_brand(settings.references_dir)
        where = brand_path(settings.references_dir)
        if where == settings.brand_file:
            checks.append(Check("ok", "brand.json",
                                f"{brand.brand_name} ({brand.status}), {where}"))
        else:
            checks.append(Check("warn", "brand.json", f"read from {where} (not in git)",
                                f"Move it to {settings.brand_file} so every machine has it."))
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
