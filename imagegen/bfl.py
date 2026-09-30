"""BFL FLUX.2 Pro submit, poll, and result-download adapter."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from .config import Config


class ProviderError(RuntimeError):
    """Safe, user-facing provider error that never includes credentials."""


@dataclass
class ProviderResult:
    provider_job_id: str
    image_bytes: bytes
    result_seed: int | None = None


def _check_status(response: requests.Response, *, operation: str) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    if status == 401:
        message = "BFL rejected the API key (HTTP 401). Check that BFL_API_KEY is correct."
    elif status == 402:
        message = "BFL reported insufficient credits (HTTP 402). Add credits to the BFL account."
    elif status == 429:
        message = "BFL rate-limited the request (HTTP 429). Wait before submitting another generation."
    elif status >= 500:
        message = f"BFL had a server error during {operation} (HTTP {status})."
    else:
        message = f"BFL rejected {operation} (HTTP {status}). Check the request parameters."
    raise ProviderError(message)


def _json_object(response: requests.Response, *, operation: str) -> dict[str, Any]:
    try:
        data = response.json()
    except (ValueError, requests.JSONDecodeError) as exc:
        raise ProviderError(f"BFL returned invalid JSON during {operation}.") from exc
    if not isinstance(data, dict):
        raise ProviderError(f"BFL returned an unexpected response during {operation}.")
    return data


def _validate_polling_url(polling_url: Any) -> str:
    if not isinstance(polling_url, str):
        raise ProviderError("BFL submission response did not include a polling URL.")
    parsed = urlparse(polling_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host.startswith("api.") or not host.endswith(".bfl.ai"):
        raise ProviderError("BFL returned an invalid polling URL; credentials were not sent to it.")
    return polling_url


def submit_poll_download(
    payload: dict[str, Any],
    config: Config,
    *,
    on_submitted: Callable[[str], None] | None = None,
    on_processing: Callable[[], None] | None = None,
    poll_timeout_seconds: int | None = None,
    session: requests.Session | Any = requests,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> ProviderResult:
    """Submit once, poll with bounded backoff, and download the expiring result URL."""
    headers = {"accept": "application/json", "x-key": config.api_key, "Content-Type": "application/json"}
    try:
        response = session.post(config.endpoint, headers=headers, json=payload, timeout=(10, 60))
    except requests.RequestException as exc:
        raise ProviderError("Could not connect to BFL while submitting the generation request.") from exc
    _check_status(response, operation="generation submission")
    submitted = _json_object(response, operation="generation submission")
    provider_job_id = submitted.get("id")
    if not isinstance(provider_job_id, (str, int)):
        raise ProviderError("BFL submission response did not include a job ID.")
    provider_job_id = str(provider_job_id)
    polling_url = _validate_polling_url(submitted.get("polling_url"))
    if on_submitted:
        on_submitted(provider_job_id)

    timeout_seconds = poll_timeout_seconds or config.poll_timeout_seconds
    started = monotonic()
    delay = 0.5
    transient_failures = 0
    while monotonic() - started < timeout_seconds:
        sleep(delay)
        if monotonic() - started >= timeout_seconds:
            break
        try:
            poll_response = session.get(polling_url, headers={"accept": "application/json", "x-key": config.api_key}, timeout=(10, 30))
            _check_status(poll_response, operation="result polling")
            result = _json_object(poll_response, operation="result polling")
            transient_failures = 0
        except ProviderError as exc:
            if "HTTP 429" in str(exc) or "server error" in str(exc):
                transient_failures += 1
                if transient_failures >= 5:
                    raise ProviderError(f"BFL polling kept failing: {exc}") from exc
                delay = min(delay * 2, 5.0)
                continue
            raise
        except requests.RequestException as exc:
            transient_failures += 1
            if transient_failures >= 5:
                raise ProviderError("BFL result polling repeatedly failed due to a network error.") from exc
            delay = min(delay * 2, 5.0)
            continue

        status = result.get("status")
        if status == "Ready":
            body = result.get("result")
            image_url = body.get("sample") if isinstance(body, dict) else None
            if not isinstance(image_url, str):
                raise ProviderError("BFL marked the job Ready but did not return a result image URL.")
            try:
                # BFL result URLs are signed and expire; they need no API key header.
                download = session.get(image_url, stream=True, timeout=(10, 60))
                _check_status(download, operation="result download")
                chunks = download.iter_content(chunk_size=1024 * 64)
                image_bytes = b"".join(chunk for chunk in chunks if chunk)
            except requests.RequestException as exc:
                raise ProviderError("Could not download the BFL result image before its temporary URL expired.") from exc
            if not image_bytes:
                raise ProviderError("BFL returned an empty result image.")
            seed = body.get("seed") if isinstance(body, dict) else None
            return ProviderResult(provider_job_id, image_bytes, seed if isinstance(seed, int) else None)
        if status in {"Error", "Failed", "Task not found", "Request Moderated", "Content Moderated"}:
            if status in {"Request Moderated", "Content Moderated"}:
                raise ProviderError(f"BFL moderated the generation request ({status}). Review the prompt and reference images.")
            raise ProviderError(f"BFL generation failed (status: {status}).")
        if status in {"Pending", "Reasoning", "Generating", "Processing", "Queued"}:
            if on_processing:
                on_processing()
            delay = min(delay * 1.6, 5.0)
            continue
        raise ProviderError(f"BFL returned an undocumented job status: {status!r}.")

    raise ProviderError(f"BFL generation timed out after {timeout_seconds} seconds.")

