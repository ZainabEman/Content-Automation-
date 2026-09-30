"""Configuration for the local BFL image generation workflow."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENDPOINT = "https://api.bfl.ai/v1/flux-2-pro"
MAX_OUTPUT_PIXELS = 4_000_000
# BFL's image best-practices guidance budgets input references plus output at 9MP.
MAX_REQUEST_PIXELS = 9_000_000
MAX_REFERENCE_IMAGES = 8
POLL_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class Config:
    api_key: str = field(repr=False)
    endpoint: str = DEFAULT_ENDPOINT
    poll_timeout_seconds: int = POLL_TIMEOUT_SECONDS


def load_config(*, require_key: bool = True) -> Config:
    """Load settings from process environment and the project-local .env file."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    api_key = os.environ.get("BFL_API_KEY", "").strip()
    endpoint = os.environ.get("BFL_ENDPOINT", DEFAULT_ENDPOINT).strip()
    timeout_text = os.environ.get("BFL_POLL_TIMEOUT_SECONDS", str(POLL_TIMEOUT_SECONDS))

    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host.startswith("api.") or not host.endswith(".bfl.ai"):
        raise ValueError("BFL_ENDPOINT must be an HTTPS BFL API URL, such as https://api.bfl.ai/v1/flux-2-pro.")
    if not parsed.path.startswith("/v1/"):
        raise ValueError("BFL_ENDPOINT must point to a documented /v1/ model endpoint.")
    try:
        timeout = int(timeout_text)
    except ValueError as exc:
        raise ValueError("BFL_POLL_TIMEOUT_SECONDS must be a positive integer.") from exc
    if timeout <= 0:
        raise ValueError("BFL_POLL_TIMEOUT_SECONDS must be a positive integer.")
    if require_key and not api_key:
        raise ValueError("BFL_API_KEY is missing. Add it to the project .env file.")
    return Config(api_key=api_key, endpoint=endpoint, poll_timeout_seconds=timeout)

