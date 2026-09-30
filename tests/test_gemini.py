import base64
import io
import json
import socket
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from content_automation.ai.image import (
    ImageProviderError,
    ImageRequest,
    ImageRequestError,
    ImageTimeoutError,
    ReferenceImage,
    get_provider,
    validate_request,
)
from content_automation.ai.image.providers import gemini
from content_automation.ai.image.providers.gemini import GeminiImageProvider, map_error
from content_automation.core.config import ConfigurationError, Settings, load_settings
from content_automation.core.limits import DailyLimitError
from content_automation.workflows.image_job import run_image_job


def png_bytes(color: tuple[int, int, int] = (0, 75, 160)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 80), color).save(buffer, format="PNG")
    return buffer.getvalue()


PNG = png_bytes()


def ok(n: int, *, via_steps: bool = False) -> SimpleNamespace:
    data = base64.b64encode(PNG).decode()
    block = SimpleNamespace(type="image", data=data, mime_type="image/png")
    if via_steps:
        step = SimpleNamespace(type="model_output", content=[block], error=None)
        return SimpleNamespace(id=f"int-{n}", status="completed", output_image=None,
                               steps=[step], errors=None, output_text="")
    return SimpleNamespace(id=f"int-{n}", status="completed", output_image=block, steps=[],
                           errors=None, output_text="")


class HttpError(Exception):
    def __init__(self, status: int, message: str = "boom") -> None:
        super().__init__(f"Error code: {status} - {message}")
        self.status_code = status


class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class FakeInteractions:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fake_factory(fake: FakeInteractions) -> Callable[[str], Any]:
    def factory(api_key: str) -> Any:
        assert api_key == "test-key"
        return SimpleNamespace(interactions=fake)

    return factory


def provider(fake: FakeInteractions) -> GeminiImageProvider:
    return GeminiImageProvider(
        "test-key", timeout_s=5, max_retries=1, client_factory=fake_factory(fake),
        sleep=lambda _: None,
    )


def ref(tmp_path: Path, name: str, content: bytes) -> ReferenceImage:
    path = tmp_path / name
    path.write_bytes(content)
    return ReferenceImage(asset_id=name.split(".")[0], path=path)


def test_network_is_blocked_in_tests() -> None:
    with pytest.raises(RuntimeError, match="Network access is disabled"):
        socket.create_connection(("generativelanguage.googleapis.com", 443))


def test_request_shape_part_order_and_images(tmp_path: Path) -> None:
    fake = FakeInteractions([ok(1), ok(2, via_steps=True)])
    request = ImageRequest(
        prompt="A person at a café",
        aspect_ratio="4:5",
        count=2,
        identity_refs=[ref(tmp_path, "id1.jpg", b"i1"), ref(tmp_path, "id2.jpg", b"i2")],
        object_refs=[ref(tmp_path, "logo.png", b"lg")],
        style_refs=[ref(tmp_path, "style.webp", b"st")],
    )

    result = provider(fake).generate(request, "gemini-3.1-flash-image")

    assert len(fake.calls) == 2
    call = fake.calls[0]
    assert call["model"] == "gemini-3.1-flash-image"
    assert call["response_format"] == {"type": "image", "aspect_ratio": "4:5", "image_size": "1K"}
    assert call["timeout"] == 5
    assert call["input"][0] == {"type": "text", "text": "A person at a café"}
    assert call["input"][1:] == [
        {"type": "image", "data": base64.b64encode(content).decode(), "mime_type": mime}
        for content, mime in (
            (b"i1", "image/jpeg"), (b"i2", "image/jpeg"), (b"lg", "image/png"),
            (b"st", "image/webp"),
        )
    ]
    assert result.provider_request_ids == ["int-1", "int-2"]
    assert [image.data for image in result.images] == [PNG, PNG]
    assert result.images[0].mime_type == "image/png"


def test_retryable_error_is_retried_per_call() -> None:
    fake = FakeInteractions([ok(1), HttpError(429), ok(2)])

    result = provider(fake).generate(ImageRequest(prompt="x", count=2), "m")

    assert len(fake.calls) == 3  # image 1 is not requested again
    assert result.provider_request_ids == ["int-1", "int-2"]


def test_server_errors_give_up_after_retries_without_outer_retry() -> None:
    fake = FakeInteractions([HttpError(503), HttpError(500)])

    with pytest.raises(ImageProviderError, match="server error") as caught:
        provider(fake).generate(ImageRequest(prompt="x"), "m")

    assert len(fake.calls) == 2
    assert caught.value.retryable is False


@pytest.mark.parametrize(
    ("error", "message", "retryable", "error_type"),
    [
        (HttpError(429), "HTTP 429", True, ImageProviderError),
        (HttpError(500), "HTTP 500", True, ImageProviderError),
        (HttpError(400, "invalid argument"), "rejected the request (HTTP 400)", False,
         ImageProviderError),
        (HttpError(403), "GEMINI_API_KEY", False, ImageProviderError),
        (APITimeoutError("slow"), "did not respond in time", False, ImageTimeoutError),
        (APIConnectionError("down"), "Could not reach Gemini", True, ImageProviderError),
    ],
)
def test_error_mapping(
    error: Exception, message: str, retryable: bool, error_type: type[Exception]
) -> None:
    mapped = map_error(error)

    assert isinstance(mapped, error_type)
    assert message in str(mapped)
    assert mapped.retryable is retryable


def test_bad_request_is_not_retried() -> None:
    fake = FakeInteractions([HttpError(400, "invalid argument")])

    with pytest.raises(ImageProviderError, match="HTTP 400"):
        provider(fake).generate(ImageRequest(prompt="x"), "m")
    assert len(fake.calls) == 1


def test_no_image_gives_clear_reason() -> None:
    blocked = SimpleNamespace(
        id="int-9", status="failed", output_image=None, steps=[],
        errors=[SimpleNamespace(message="Blocked by safety filters")],
        output_text="I can't create that image.",
    )
    fake = FakeInteractions([blocked])

    with pytest.raises(ImageProviderError) as caught:
        provider(fake).generate(ImageRequest(prompt="x"), "m")

    text = str(caught.value)
    assert "no image" in text and "Blocked by safety filters" in text
    assert "status: failed" in text and "I can't create that image" in text
    assert caught.value.retryable is False
    assert len(fake.calls) == 1


def test_invalid_image_data_is_rejected() -> None:
    bad = ok(1)
    bad.output_image.data = base64.b64encode(b"not an image").decode()

    with pytest.raises(ImageProviderError, match="not a valid image"):
        provider(FakeInteractions([bad])).generate(ImageRequest(prompt="x"), "m")


@pytest.mark.usefixtures("clean_env")
def test_missing_key_fails_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def must_not_run(_: str) -> Any:
        raise AssertionError("client created")

    adapter = GeminiImageProvider(None, client_factory=must_not_run)
    with pytest.raises(ImageProviderError, match="GEMINI_API_KEY missing"):
        adapter.generate(ImageRequest(prompt="x"), "m")

    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY missing"):
        load_settings(env_file=None, create_directories=False)


def _refs(n: int) -> list[ReferenceImage]:
    return [ReferenceImage(asset_id=f"a{i}", path=Path(f"a{i}.jpg")) for i in range(n)]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"identity_refs": _refs(5)}, "5 identity references (max 4)"),
        ({"style_refs": _refs(4)}, "4 style references (max 3)"),
        ({"object_refs": _refs(8), "style_refs": _refs(3)}, "11 product/brand/style"),
        ({"object_refs": _refs(11)}, "11 object references (max 10)"),
    ],
)
def test_capability_caps(kwargs: dict[str, list[ReferenceImage]], message: str) -> None:
    capabilities = get_provider("gemini").capabilities

    with pytest.raises(ImageRequestError, match=message.replace("(", r"\(").replace(")", r"\)")):
        validate_request(ImageRequest(prompt="x", **kwargs), capabilities)
    validate_request(
        ImageRequest(
            prompt="x", identity_refs=_refs(4), object_refs=_refs(7), style_refs=_refs(3)
        ),
        capabilities,
    )


@pytest.fixture
def gemini_settings(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> tuple[Settings, FakeInteractions]:
    fake = FakeInteractions([ok(1), ok(2)])
    monkeypatch.setattr(gemini, "_google_client", fake_factory(fake))
    settings = make_settings(
        image_provider="gemini", gemini_api_key="test-key", image_daily_limit="3"
    )
    return settings, fake


def test_job_records_cost_ids_and_counts_toward_limit(
    gemini_settings: tuple[Settings, FakeInteractions],
) -> None:
    settings, fake = gemini_settings

    job = run_image_job(ImageRequest(prompt="x", count=2), settings)

    data = json.loads((job.folder / "details.json").read_text(encoding="utf-8"))
    assert data["status"] == "completed"
    assert data["provider"] == "gemini"
    assert data["estCostUsd"] == pytest.approx(0.134)
    assert data["providerRequestIds"] == ["int-1", "int-2"]
    assert (job.folder / "image-1.png").read_bytes() == PNG
    with pytest.raises(DailyLimitError, match="2 of 3"):
        run_image_job(ImageRequest(prompt="y", count=2), settings)
    assert len(fake.calls) == 2


def test_key_never_reaches_details(
    gemini_settings: tuple[Settings, FakeInteractions],
) -> None:
    settings, fake = gemini_settings
    fake.responses = [HttpError(400, "bad key test-key in request")]

    job = run_image_job(ImageRequest(prompt="x"), settings)

    text = (job.folder / "details.json").read_text(encoding="utf-8")
    assert job.status == "failed"
    assert "test-key" not in text and "***" in text
