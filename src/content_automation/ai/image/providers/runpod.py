"""RunPod Serverless client for a runpod-workers/worker-comfyui endpoint (README checked
2026-10-10, release 5.11.0; see docs/PHASE2-DECISION.md).

    POST {API}/{endpoint}/run          {"input": {"workflow": {...}}}  -> {"id", "status"}
    GET  {API}/{endpoint}/status/{id}  -> {"status", "delayTime", "executionTime", "output",
                                           "error"}
    POST {API}/{endpoint}/cancel/{id}  when our time budget ends, so the GPU stops billing

``output.images`` is a list of {"filename", "type": "base64" | "s3_url", "data"};
``output.errors`` lists non-fatal problems. Times are milliseconds.

Nothing here retries a generation: a failed or timed-out job is reported, never sent again.
Only a status poll that hits a network error is repeated (it costs nothing).
"""

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from content_automation.ai.image import ImageProviderError, ImageTimeoutError

API_URL = "https://api.runpod.ai/v2"
FINAL_STATES = ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT")
MAX_POLL_ERRORS = 3  # network errors in a row while polling before we give up
_HTTP_TIMEOUT_S = 30.0
_DETAIL_LIMIT = 300
SWITCH = "To use Nano Banana instead, switch with IMAGE_PROVIDER=openrouter (new dry run first)."


@dataclass
class RunPodJob:
    job_id: str
    status: str
    output: Any = None
    error: str | None = None
    delay_ms: float = 0.0  # queue and cold start
    execution_ms: float = 0.0
    images: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _short(text: object) -> str:
    return " ".join(str(text).split())[:_DETAIL_LIMIT]


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


class RunPodClient:
    def __init__(
        self,
        api_key: str,
        endpoint_id: str,
        *,
        poll_s: float,
        timeout_s: float,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._base = f"{API_URL}/{endpoint_id}"
        self._poll_s = poll_s
        self._timeout_s = timeout_s
        self._transport = transport
        self._sleep = sleep
        self._clock = clock

    def run(self, workflow: dict[str, Any]) -> RunPodJob:
        """Submit one workflow and wait for its final state (cancelled after timeout_s)."""
        with httpx.Client(timeout=_HTTP_TIMEOUT_S, transport=self._transport) as client:
            job_id = self._submit(client, workflow)
            deadline = self._clock() + self._timeout_s
            errors = 0
            while True:
                try:
                    job = self._status(client, job_id)
                    errors = 0
                except ImageProviderError:
                    self._cancel(client, job_id)
                    raise
                except httpx.TransportError as error:
                    errors += 1
                    if errors >= MAX_POLL_ERRORS:
                        self._cancel(client, job_id)
                        raise ImageProviderError(
                            f"Lost contact with RunPod while waiting for job {job_id} "
                            f"({type(error).__name__}); the job was cancelled. {SWITCH}"
                        ) from None
                    job = None
                if job is not None and job.status in FINAL_STATES:
                    return job
                if self._clock() >= deadline:
                    self._cancel(client, job_id)
                    raise ImageTimeoutError(
                        f"RunPod job {job_id} did not finish within {self._timeout_s:g} s "
                        "(timeoutSeconds in config/comfyui.json); it was cancelled so the GPU "
                        f"stops billing. {SWITCH}"
                    )
                self._sleep(self._poll_s)

    def _submit(self, client: httpx.Client, workflow: dict[str, Any]) -> str:
        try:
            response = client.post(
                f"{self._base}/run", headers=self._headers, json={"input": {"workflow": workflow}}
            )
        except httpx.TimeoutException:
            raise ImageTimeoutError(
                f"RunPod did not accept the job in time. {SWITCH}"
            ) from None
        except httpx.TransportError as error:
            raise ImageProviderError(
                f"Could not reach RunPod ({type(error).__name__}). {SWITCH}"
            ) from None
        payload = self._json(response)
        job_id = payload.get("id")
        if not isinstance(job_id, str) or not job_id:
            raise ImageProviderError(f"RunPod returned no job ID: {_short(payload)}. {SWITCH}")
        return job_id

    def _status(self, client: httpx.Client, job_id: str) -> RunPodJob:
        response = client.get(f"{self._base}/status/{job_id}", headers=self._headers)
        payload = self._json(response)
        output = payload.get("output")
        images: list[dict[str, Any]] = []
        warnings: list[str] = []
        if isinstance(output, dict):
            found = output.get("images")
            if isinstance(found, list):
                images = [item for item in found if isinstance(item, dict)]
            reported = output.get("errors")
            if isinstance(reported, list):
                warnings = [_short(item) for item in reported]
        error = payload.get("error")
        if error is None and isinstance(output, dict) and output.get("error"):
            error = output.get("error")
        return RunPodJob(
            job_id=job_id,
            status=str(payload.get("status", "")),
            output=output,
            error=_short(error) if error else None,
            delay_ms=_number(payload.get("delayTime")),
            execution_ms=_number(payload.get("executionTime")),
            images=images,
            warnings=warnings,
        )

    def _cancel(self, client: httpx.Client, job_id: str) -> None:
        """Best effort: the job may already be finished."""
        with contextlib.suppress(httpx.HTTPError):
            client.post(f"{self._base}/cancel/{job_id}", headers=self._headers)

    def download(self, url: str) -> bytes:
        """An image the worker uploaded to S3 (type s3_url) instead of returning base64."""
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_S, transport=self._transport) as client:
                response = client.get(url)
        except httpx.HTTPError as error:
            raise ImageProviderError(
                f"Could not download the image from the worker's S3 bucket "
                f"({type(error).__name__}). {SWITCH}"
            ) from None
        if response.status_code != 200 or not response.content:
            raise ImageProviderError(
                f"The worker's S3 image could not be downloaded (HTTP {response.status_code})."
            )
        return response.content

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code == 401:
            raise ImageProviderError(
                "RunPod rejected the API key (HTTP 401); check RUNPOD_API_KEY in .env."
            )
        if response.status_code == 404:
            raise ImageProviderError(
                "RunPod does not know this endpoint or job (HTTP 404); check RUNPOD_ENDPOINT_ID "
                "in .env."
            )
        if response.status_code != 200 or not isinstance(payload, dict):
            detail = _short(payload if payload is not None else response.text) or "no details"
            raise ImageProviderError(
                f"RunPod request failed (HTTP {response.status_code}): {detail}. {SWITCH}"
            )
        return payload
