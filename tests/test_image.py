import io
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from content_automation.ai.image import (
    ImageProviderError,
    ImageRequest,
    ImageRequestError,
    ImageTimeoutError,
    ReferenceImage,
    UnknownImageProviderError,
    available_providers,
    generate_image,
    get_provider,
)
from content_automation.core.config import Settings
from content_automation.workflows.image_job import run_image_job

SettingsFactory = Callable[..., Settings]


def _refs(count: int, prefix: str) -> list[ReferenceImage]:
    return [
        ReferenceImage(asset_id=f"{prefix}{i}", path=Path(f"{prefix}{i}.jpg"))
        for i in range(count)
    ]


def test_registry_picks_mock_and_rejects_unknown() -> None:
    assert get_provider("mock").name == "mock"
    with pytest.raises(UnknownImageProviderError, match="IMAGE_PROVIDER"):
        get_provider("nope")


def test_registry_lists_all_image_providers() -> None:
    assert available_providers() == ("mock", "openrouter")


@pytest.mark.parametrize(
    ("aspect", "size"), [("1:1", (1024, 1024)), ("4:5", (819, 1024)), ("9:16", (576, 1024)),
                         ("16:9", (1024, 576))]
)
def test_mock_renders_png_at_aspect(
    make_settings: SettingsFactory, aspect: str, size: tuple[int, int]
) -> None:
    request = ImageRequest(prompt="A café scene", aspect_ratio=aspect, count=2)  # type: ignore[arg-type]

    result = generate_image(request, settings=make_settings())

    assert result.provider == "mock"
    assert len(result.images) == 2
    with Image.open(io.BytesIO(result.images[0].data)) as image:
        assert image.format == "PNG"
        assert image.size == size


def test_mock_fail_and_timeout(make_settings: SettingsFactory) -> None:
    request = ImageRequest(prompt="x")
    with pytest.raises(ImageProviderError, match="mock-fail"):
        generate_image(request, settings=make_settings(image_model="mock-fail"))
    with pytest.raises(ImageTimeoutError):
        generate_image(request, settings=make_settings(image_model="mock-timeout"))


@pytest.mark.parametrize(
    "request_kwargs",
    [
        {"identity_refs": _refs(5, "id")},
        {"object_refs": _refs(11, "obj")},
        {"style_refs": _refs(11, "sty")},
    ],
)
def test_over_limit_refs_rejected_before_call(
    make_settings: SettingsFactory,
    monkeypatch: pytest.MonkeyPatch,
    request_kwargs: dict[str, list[ReferenceImage]],
) -> None:
    provider_type = type(get_provider("mock"))

    def must_not_run(*_: object) -> None:
        raise AssertionError("provider was called")

    monkeypatch.setattr(provider_type, "generate", must_not_run)
    with pytest.raises(ImageRequestError, match="max"):
        generate_image(ImageRequest(prompt="x", **request_kwargs), settings=make_settings())


def test_run_image_job_completes(make_settings: SettingsFactory) -> None:
    request = ImageRequest(prompt="Sara at a café", aspect_ratio="4:5", count=3,
                           identity_refs=_refs(2, "id"), style_refs=_refs(1, "sty"))
    job = run_image_job(request, make_settings(), user_request="3 options of Sara")

    assert job.status == "completed"
    assert job.outputs == ["image-1.png", "image-2.png", "image-3.png"]
    data = json.loads((job.folder / "details.json").read_text(encoding="utf-8"))
    assert data["status"] == "completed"
    assert data["identityAssetIds"] == ["id0", "id1"]
    assert data["styleAssetIds"] == ["sty0"]
    assert data["request"] == "3 options of Sara"
    assert data["providerRequestIds"]


def test_run_image_job_records_failure_without_images(make_settings: SettingsFactory) -> None:
    job = run_image_job(ImageRequest(prompt="x", count=2), make_settings(image_model="mock-fail"))

    assert job.status == "failed"
    assert "mock-fail" in (job.error or "")
    assert not list(job.folder.glob("image-*"))


def test_mock_images_do_not_count_toward_daily_limit(make_settings: SettingsFactory) -> None:
    settings = make_settings(image_daily_limit="3")

    first = run_image_job(ImageRequest(prompt="x", count=3), settings)
    second = run_image_job(ImageRequest(prompt="y", count=3), settings)

    assert first.status == second.status == "completed"
