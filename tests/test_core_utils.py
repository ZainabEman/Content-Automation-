import logging
import socket
import time
from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr

from content_automation.core.config import Settings
from content_automation.core.jobs import JobParams, create_job
from content_automation.core.limits import DailyLimitError, check_daily_limit, images_generated_on
from content_automation.core.log import SecretMaskingFormatter, mask_secrets, secret_values
from content_automation.core.retry import OperationTimeoutError, call_with_retry, run_with_timeout


class _Temporary(Exception):
    retryable = True


class _Permanent(Exception):
    pass


def test_retry_retries_only_retryable_errors() -> None:
    calls: list[int] = []
    delays: list[float] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise _Temporary("busy")
        return "ok"

    assert call_with_retry(flaky, timeout_s=5, max_retries=2, sleep=delays.append) == "ok"
    assert len(calls) == 3
    assert delays == [2.0, 4.0]


def test_retry_gives_up_after_max_retries() -> None:
    calls: list[int] = []

    def always_busy() -> None:
        calls.append(1)
        raise _Temporary("busy")

    with pytest.raises(_Temporary):
        call_with_retry(always_busy, timeout_s=5, max_retries=1, sleep=lambda _: None)
    assert len(calls) == 2


def test_retry_does_not_retry_permanent_errors() -> None:
    calls: list[int] = []

    def broken() -> None:
        calls.append(1)
        raise _Permanent("bad request")

    with pytest.raises(_Permanent):
        call_with_retry(broken, timeout_s=5, max_retries=3, sleep=lambda _: None)
    assert len(calls) == 1


def test_timeout_raises() -> None:
    with pytest.raises(OperationTimeoutError):
        run_with_timeout(lambda: time.sleep(1), timeout_s=0.05)


def _completed_job(output_dir: Path, images: int, provider: str = "openrouter") -> None:
    job = create_job(
        output_dir,
        workflow_id="direct",
        workflow_version="1",
        requested_by="Tester",
        request="x",
        prompt="x",
        provider=provider,
        model="m",
        params=JobParams(aspect_ratio="1:1", image_size="1K", count=images),
    )
    names = []
    for index in range(1, images + 1):
        (job.folder / f"image-{index}.png").write_bytes(b"png")
        names.append(f"image-{index}.png")
    job.complete(names)


def test_daily_limit_counts_completed_images_today(tmp_path: Path) -> None:
    _completed_job(tmp_path, 3)
    _completed_job(tmp_path, 4, provider="mock")  # free test images are not counted
    failed = create_job(
        tmp_path, workflow_id="direct", workflow_version="1", requested_by="T", request="y",
        prompt="y", provider="openrouter", model="m",
        params=JobParams(aspect_ratio="1:1", image_size="1K", count=4),
    )
    failed.fail("boom")

    assert images_generated_on(tmp_path, date.today()) == 3
    assert check_daily_limit(tmp_path, limit=5, requested=2) == 0
    with pytest.raises(DailyLimitError, match="3 of 5"):
        check_daily_limit(tmp_path, limit=5, requested=3)


def test_logger_masks_secrets() -> None:
    settings = Settings(openrouter_api_key=SecretStr("synthetic-key-123"), _env_file=None)  # type: ignore[call-arg]
    secrets = secret_values(settings)
    formatter = SecretMaskingFormatter(secrets, "%(message)s")
    record = logging.LogRecord("t", logging.INFO, "f", 1, "key=%s", ("synthetic-key-123",), None)

    assert formatter.format(record) == "key=***"
    assert mask_secrets("x synthetic-key-123 y", secrets) == "x *** y"


def test_network_is_blocked_in_tests() -> None:
    with pytest.raises(RuntimeError, match="Network access is disabled"):
        socket.create_connection(("openrouter.ai", 443))
