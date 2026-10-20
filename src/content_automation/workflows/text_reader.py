"""v6 (PRD R3.4): read the text in a finished image, for the exact-text verification.

`openrouter`: a vision check through the configured provider (POST /api/v1/chat/completions with
the image as a data URL; the model is config/designer_prompts.json textCheck.model, or the
configured image model when that is null), asked for text only. Its cost is in the dry run
(textCheck.estimatedUsd per check, not calibrated: PRD v6 §7) and `usage.cost` is recorded as
the actual. `mock` (IMAGE_PROVIDER=mock and the tests): reads a sidecar `<image>.read.json` when
one exists, else returns the intended text, so a local run passes; it never calls anything.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
from PIL import Image

from content_automation.core.config import Settings
from content_automation.core.parallel import released
from content_automation.workflows.image_check import ReadText

API_URL = "https://openrouter.ai/api/v1/chat/completions"
_LONG_SIDE = 1536  # the image sent for reading (enough for small print, cheaper than 2K)


class TextReadError(RuntimeError):
    """The text could not be read (the vision check failed). service: the check service itself
    failed (timeout, 429, 5xx, a bad response): retried once, never an image attempt."""

    def __init__(self, message: str, *, service: bool = True) -> None:
        super().__init__(message)
        self.service = service


@dataclass
class TextRead:
    texts: list[ReadText] = field(default_factory=list)
    cost_usd: float | None = None
    reader: str = "mock"


class TextReader(Protocol):
    name: str

    def read(self, image: Image.Image, intended: list[str]) -> TextRead: ...


class MockTextReader:
    """Offline: the intended text (or a recorded reading for a test)."""

    name = "mock"

    def __init__(self, recorded: list[str] | None = None) -> None:
        self._recorded = recorded

    def read(self, image: Image.Image, intended: list[str]) -> TextRead:
        del image
        lines = self._recorded if self._recorded is not None else list(intended)
        return TextRead([ReadText(line) for line in lines], 0.0, self.name)


class OpenRouterTextReader:
    """The vision check: one chat completion with the image, text out."""

    name = "openrouter"

    def __init__(self, api_key: str | None, model: str, prompt: str, *, timeout_s: float = 90.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._prompt = prompt
        self._timeout_s = timeout_s
        self._transport = transport

    def read(self, image: Image.Image, intended: list[str]) -> TextRead:
        del intended  # never shown to the model: it must read, not confirm
        if not self._api_key:
            raise TextReadError("OPENROUTER_API_KEY missing: the text check cannot run",
                                service=False)
        copy = image.convert("RGB")
        copy.thumbnail((_LONG_SIDE, _LONG_SIDE))
        buffer = io.BytesIO()
        copy.save(buffer, format="PNG")
        url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        body: dict[str, Any] = {
            "model": self._model, "modalities": ["text"], "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": self._prompt},
                {"type": "image_url", "image_url": {"url": url}}]}],
            "usage": {"include": True},
        }
        try:
            with (httpx.Client(timeout=self._timeout_s, transport=self._transport) as client,
                  released()):  # a parallel build: the others run meanwhile
                response = client.post(API_URL, json=body,
                                       headers={"Authorization": f"Bearer {self._api_key}"})
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise TextReadError(f"the text check could not reach OpenRouter "
                                f"({type(error).__name__})") from None
        if response.status_code != 200 or not isinstance(payload, dict) or payload.get("error"):
            status = response.status_code
            raise TextReadError(f"the text check failed (HTTP {status})",
                                service=status == 200 or status == 429 or status >= 500)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise TextReadError("the text check returned no text") from None
        text = content if isinstance(content, str) else " ".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict))
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines == ["NONE"]:
            lines = []
        usage = payload.get("usage")
        cost = usage.get("cost") if isinstance(usage, dict) else None
        return TextRead([ReadText(line) for line in lines],
                        float(cost) if isinstance(cost, (int, float)) else None, self.name)


def text_check_config() -> dict[str, Any]:
    from content_automation.content.designer_prompt import load_templates

    config = load_templates().get("textCheck", {})
    return config if isinstance(config, dict) else {}


def reader_for(settings: Settings, image_path: Path | None = None) -> TextReader:
    """The reader of a run: mock on the mock provider (a sidecar reading wins), else the
    OpenRouter vision check with the configured model."""
    if settings.image_provider in ("mock", "template"):
        sidecar = image_path.with_suffix(".read.json") if image_path is not None else None
        if sidecar is not None and sidecar.is_file():
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            return MockTextReader([str(item) for item in data])
        return MockTextReader()
    config = text_check_config()  # a vision chat model: gpt-image-2 only makes images
    model = str(config.get("model") or settings.carousel_image_model)
    key = settings.openrouter_api_key.get_secret_value() if settings.openrouter_api_key else None
    return OpenRouterTextReader(key, model, str(config.get("prompt", "")))


def estimated_check_usd() -> float:
    return float(text_check_config().get("estimatedUsd", 0.0))


__all__ = ["MockTextReader", "OpenRouterTextReader", "TextRead", "TextReadError", "TextReader",
           "estimated_check_usd", "reader_for", "text_check_config"]
