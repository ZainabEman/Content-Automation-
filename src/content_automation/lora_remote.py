"""`ca lora train-remote`: train the person's LoRA on a temporary RunPod Pod in one command.

The path (RunPod docs checked 2026-10-10, see docs/PHASE2-DECISION.md):

1. The dataset, the AI Toolkit YAMLs and a start script go onto the network volume through its
   S3-compatible API (bucket = the volume ID, one endpoint per datacenter).
2. A Pod is created with the REST API (POST /v1/pods): AI Toolkit's template, an L40S, the
   network volume at /workspace and the script as start command. It trains the models one after
   another into lora/output/<run>/ (checkpoints + samples), copies every .safetensors to
   models/loras/ as <run>_<file>, writes lora/runs/<run>/status and terminates itself.
3. This computer watches it: the Pod (GET /v1/pods/{id}), the status file and new sample images
   (S3, saved to outputs/lora/<model>/samples/<run>/step_<n>/). outputs/lora/runs/<run>/
   train.json records the run, with the cost from the Pod's costPerHr and the time it ran.

Safety: one Pod at a time (the local record and the account's Pods named with the prefix); a
hard limit (remote.maxHours) after which this computer terminates the Pod, as it also does on
Ctrl+C or any error while watching; the script has its own, slightly shorter limit and
terminates the Pod itself on failure; a Pod that reports finished but still runs after
finishGraceSeconds is terminated. Nothing starts without the user's "ok" on the estimate (--yes).
"""

import re
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import Field, SecretStr

from content_automation.core.config import Settings
from content_automation.core.files import CamelModel, atomic_write_text
from content_automation.lora import (
    OUT_DIR,
    LoraConfig,
    LoraError,
    ModelKey,
    check_consent,
    job_name,
    load_lora_config,
    newest_dataset,
    prepare_dataset,
    training_config,
)

REST_URL = "https://rest.runpod.io/v1"
RUNS_DIR = OUT_DIR / "runs"
RUN_FILE = "train.json"
ACTIVE = ("starting", "running")
FINISHED = ("done", "failed", "stopped")
_POD_LIMIT_MARGIN_S = 600  # the Pod's own limit ends this much before ours
_MAX_POLL_FAILURES = 3  # then it counts as an error: the Pod is terminated
_SAMPLE = re.compile(r"__(\d+)_(\d+)\.(?:jpg|jpeg|png|webp)$", re.IGNORECASE)
_HTTP_TIMEOUT_S = 60.0
Echo = Callable[[str], None]

# Runs inside the Pod (bash). All values come from the environment: CA_RUN_ID, CA_JOBS,
# CA_LIMIT_SECONDS, plus RunPod's RUNPOD_POD_ID and Pod-scoped RUNPOD_API_KEY.
TRAIN_SCRIPT = r"""#!/bin/bash
# Written by `ca lora train-remote`; runs inside the RunPod Pod, then terminates the Pod.
set -u
RUN_DIR=/workspace/lora/runs/$CA_RUN_ID
OUT=/workspace/lora/output/$CA_RUN_ID
STATUS=$RUN_DIR/status
mkdir -p "$RUN_DIR" "$OUT" /workspace/models/loras
exec >>"$RUN_DIR/log.txt" 2>&1

terminate_self() {
  sync
  runpodctl config --apiKey "${RUNPOD_API_KEY:-}" >/dev/null 2>&1 || true
  while true; do
    echo "$(date -u +%FT%TZ) terminating Pod $RUNPOD_POD_ID"
    runpodctl pod delete "$RUNPOD_POD_ID" || runpodctl remove pod "$RUNPOD_POD_ID" || \
      curl -fsS -X DELETE -H "Authorization: Bearer ${RUNPOD_API_KEY:-}" \
        "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID"
    sleep 60
  done
}

case "$(cat "$STATUS" 2>/dev/null)" in
  done*|failed*|stopped*) echo "run already finished: terminating"; terminate_self ;;
esac

echo "starting" > "$STATUS"
export HF_HOME=/root/.cache/huggingface  # base models on the container disk, not the volume
TOOLKIT=""
for DIR in /app/ai-toolkit /ai-toolkit /workspace/ai-toolkit /root/ai-toolkit; do
  if [ -f "$DIR/run.py" ]; then TOOLKIT=$DIR; break; fi
done
if [ -z "$TOOLKIT" ]; then
  FOUND=$(find / -maxdepth 4 -name run.py -path '*ai-toolkit*' 2>/dev/null | head -n 1)
  [ -n "$FOUND" ] && TOOLKIT=$(dirname "$FOUND")
fi
if [ -z "$TOOLKIT" ]; then
  echo "failed: AI Toolkit (run.py) not found in the Pod image" > "$STATUS"
  terminate_self
fi
PYTHON=python3
[ -x "$TOOLKIT/venv/bin/python" ] && PYTHON=$TOOLKIT/venv/bin/python
cd "$TOOLKIT" || { echo "failed: cannot enter $TOOLKIT" > "$STATUS"; terminate_self; }
END=$(( $(date +%s) + CA_LIMIT_SECONDS ))
for JOB in $CA_JOBS; do
  REMAIN=$(( END - $(date +%s) ))
  if [ "$REMAIN" -le 120 ]; then
    echo "failed: time limit reached before $JOB" > "$STATUS"
    terminate_self
  fi
  echo "running: training $JOB" > "$STATUS"
  if ! timeout --kill-after=120 "$REMAIN" "$PYTHON" run.py "$RUN_DIR/$JOB.yaml"; then
    echo "failed: $JOB did not finish (time limit or error, see log.txt)" > "$STATUS"
    terminate_self
  fi
  for FILE in "$OUT/$JOB"/*.safetensors; do
    [ -f "$FILE" ] && cp "$FILE" "/workspace/models/loras/${CA_RUN_ID}_$(basename "$FILE")"
  done
done
echo "done" > "$STATUS"
terminate_self
"""


def _now() -> datetime:
    return datetime.now(UTC)


class TrainRun(CamelModel):
    """outputs/lora/runs/<run>/train.json: one remote training run."""

    run_id: str
    models: list[ModelKey]
    jobs: dict[str, str]  # model -> AI Toolkit job name (also the LoRA file name)
    dataset: str
    pod_id: str | None = None
    pod_name: str = ""
    status: str = "starting"  # starting, running, done, failed: ..., stopped: ...
    remote_status: str = ""  # what the Pod's script wrote last
    created_at: datetime | None = None  # the Pod was created (billing starts)
    ended_at: datetime | None = None
    finished_seen_at: datetime | None = None  # the script reported done/failed
    max_hours: float
    cost_per_hr: float | None = None  # from RunPod when the Pod was created
    estimate_usd: float
    max_usd: float
    actual_usd: float | None = None  # cost per hour x the time the Pod existed
    checkpoints: dict[str, list[str]] = Field(default_factory=dict)  # in models/loras/
    samples: dict[str, str] = Field(default_factory=dict)  # model -> local folder
    notes: list[str] = Field(default_factory=list)

    @property
    def folder(self) -> Path:
        return RUNS_DIR / self.run_id

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self.folder / RUN_FILE, self.model_dump_json(by_alias=True, indent=2) + "\n"
        )


def latest_run() -> TrainRun | None:
    found = sorted(RUNS_DIR.glob(f"*/{RUN_FILE}"))
    if not found:
        return None
    return TrainRun.model_validate_json(found[-1].read_text(encoding="utf-8"))


# --- RunPod REST -----------------------------------------------------------------------------


class RunPodRest:
    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._transport = transport

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_S, transport=self._transport) as client:
                response = client.request(
                    method, f"{REST_URL}{path}", headers=self._headers, json=body
                )
        except httpx.HTTPError as error:
            raise LoraError(f"Could not reach the RunPod API ({type(error).__name__}).") from None
        if response.status_code == 404:
            return None
        if response.status_code == 401:
            raise LoraError(
                "RunPod rejected RUNPOD_API_KEY (HTTP 401); the key needs read/write access to "
                "Pods and network volumes."
            )
        if response.status_code >= 400:
            detail = " ".join(response.text.split())[:300] or "no details"
            raise LoraError(
                f"RunPod API {method} {path} failed (HTTP {response.status_code}): {detail}. "
                "No credit on the account also shows up here."
            )
        return response.json() if response.content else None

    def volume(self, volume_id: str) -> dict[str, Any]:
        found = self._call("GET", f"/networkvolumes/{volume_id}")
        if not isinstance(found, dict):
            raise LoraError(
                f"Network volume {volume_id} not found; check RUNPOD_NETWORK_VOLUME_ID."
            )
        return found

    def create_pod(self, body: dict[str, Any]) -> dict[str, Any]:
        created = self._call("POST", "/pods", body)
        if not isinstance(created, dict) or not created.get("id"):
            raise LoraError("RunPod did not return a Pod ID.")
        return created

    def pod(self, pod_id: str) -> dict[str, Any] | None:
        found = self._call("GET", f"/pods/{pod_id}")
        return found if isinstance(found, dict) else None

    def pods(self) -> list[dict[str, Any]]:
        found = self._call("GET", "/pods")
        return [pod for pod in found if isinstance(pod, dict)] if isinstance(found, list) else []

    def delete_pod(self, pod_id: str) -> None:
        self._call("DELETE", f"/pods/{pod_id}")


# --- The network volume through S3 -----------------------------------------------------------


class VolumeStore:
    """The network volume as an S3 bucket (bucket = volume ID)."""

    def __init__(self, volume_id: str, datacenter: str, access_key: str, secret_key: str) -> None:
        import boto3  # heavy: only when a remote run needs it
        from botocore.config import Config

        self._bucket = volume_id
        self._s3 = boto3.client(
            "s3",
            endpoint_url=f"https://s3api-{datacenter.lower()}.runpod.io/",
            region_name=datacenter,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(read_timeout=600, retries={"max_attempts": 3}),
        )

    def _guard(self, action: str, call: Callable[[], Any]) -> Any:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return call()
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                return None
            raise LoraError(
                f"Network volume S3 {action} failed ({code or 'error'}); check the S3 API key "
                "and that the volume's datacenter supports the S3 API."
            ) from None
        except BotoCoreError as error:
            raise LoraError(
                f"Network volume S3 {action} failed ({type(error).__name__})."
            ) from None

    def put(self, key: str, data: bytes) -> None:
        self._guard("upload", lambda: self._s3.put_object(Bucket=self._bucket, Key=key, Body=data))

    def read_text(self, key: str) -> str | None:
        found = self._guard(
            "read", lambda: self._s3.get_object(Bucket=self._bucket, Key=key)
        )
        return found["Body"].read().decode("utf-8", "replace").strip() if found else None

    def keys(self, prefix: str) -> list[str]:
        def listing() -> list[str]:
            found: list[str] = []
            pages = self._s3.get_paginator("list_objects_v2").paginate(
                Bucket=self._bucket, Prefix=prefix
            )
            for page in pages:
                found += [str(item["Key"]) for item in page.get("Contents", [])]
            return found

        return list(self._guard("list", listing) or [])

    def download(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._guard("download", lambda: self._s3.download_file(self._bucket, key, str(path)))


# --- Plan, start, watch, stop ----------------------------------------------------------------


@dataclass
class Plan:
    models: list[ModelKey]
    hours: float
    estimate_usd: float
    max_usd: float
    lines: list[str]


def _models(choice: str) -> list[ModelKey]:
    if choice == "both":
        return ["qwen", "zimage"]
    if choice in ("qwen", "zimage"):
        return ["qwen"] if choice == "qwen" else ["zimage"]
    raise LoraError("--model must be qwen, zimage or both.")


def _text(value: SecretStr | str | None) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value().strip()
    return (value or "").strip()


def _missing(settings: Settings) -> list[str]:
    values: dict[str, SecretStr | str | None] = {
        "RUNPOD_API_KEY": settings.runpod_api_key,
        "RUNPOD_NETWORK_VOLUME_ID": settings.runpod_network_volume_id,
        "RUNPOD_S3_ACCESS_KEY": settings.runpod_s3_access_key,
        "RUNPOD_S3_SECRET_KEY": settings.runpod_s3_secret_key,
    }
    return [name for name, value in values.items() if not _text(value)]


def plan(settings: Settings, choice: str, echo: Echo) -> Plan:
    """Consent, dataset (made if missing) and the estimate; nothing is uploaded or started."""
    config = load_lora_config(settings.lora_config_file)
    models = _models(choice)
    echo(check_consent(settings.references_dir / config.identity_set, config.consent_file))
    try:
        dataset = newest_dataset()
    except LoraError:
        echo("No dataset yet: running `ca lora prepare`.")
        result = prepare_dataset(settings)
        for line in result.lines:
            echo(line)
        dataset = newest_dataset()
    for model in models:
        job_name(settings, model)  # the trigger word and workflow are valid
    pod, remote = config.pod, config.remote
    hours = pod.setup_hours + sum(config.models[model].training_hours for model in models)
    estimate = round(pod.price_per_hour_usd * hours, 2)
    cap = round(pod.price_per_hour_usd * remote.max_hours, 2)
    if hours > remote.max_hours:
        raise LoraError(
            f"The estimate ({hours:g} h) is over the hard limit remote.maxHours "
            f"({remote.max_hours:g} h) in config/lora.json: train one model at a time or raise "
            "the limit."
        )
    lines = [f"Dataset: {dataset.name}"]
    for model in models:
        spec = config.models[model]
        lines.append(f"  {model} ({spec.workflow}): {spec.steps} steps, about "
                     f"{spec.training_hours:g} h")
    lines += [
        f"Estimate (not a quote): {pod.gpu} at ${pod.price_per_hour_usd:.2f}/h x {hours:g} h "
        f"({pod.setup_hours:g} h setup + training) = ${estimate:.2f}.",
        f"Hard limit: {remote.max_hours:g} h, so at most about ${cap:.2f}; then the Pod is "
        "terminated (by this computer and by the Pod itself).",
    ]
    missing = _missing(settings)
    if missing:
        lines.append(f"Missing in .env before it can start: {', '.join(missing)}.")
    return Plan(models, hours, estimate, cap, lines)


def _clients(settings: Settings) -> tuple[RunPodRest, str]:
    missing = _missing(settings)
    if missing:
        raise LoraError(
            f"{', '.join(missing)} missing in .env (see docs/guides/runpod-comfyui.md, section 8)."
        )
    return RunPodRest(_text(settings.runpod_api_key)), _text(settings.runpod_network_volume_id)


def _store(settings: Settings, rest: RunPodRest, volume_id: str) -> VolumeStore:
    volume = rest.volume(volume_id)
    datacenter = str(volume.get("dataCenterId") or "")
    if not datacenter:
        raise LoraError(f"RunPod returned no datacenter for network volume {volume_id}.")
    return VolumeStore(
        volume_id,
        datacenter,
        _text(settings.runpod_s3_access_key),
        _text(settings.runpod_s3_secret_key),
    )


def _ensure_single(rest: RunPodRest, config: LoraConfig) -> None:
    """Never a second Pod: the local record and the account's Pods named with the prefix."""
    run = latest_run()
    if run is not None and run.status in ACTIVE and run.pod_id:
        pod = rest.pod(run.pod_id)
        if pod is not None and pod.get("desiredStatus") != "TERMINATED":
            raise LoraError(
                f"Run {run.run_id} (Pod {run.pod_id}) is still running: check it with "
                "`uv run ca lora status` or end it with `uv run ca lora stop`."
            )
    prefix = config.remote.name_prefix
    busy = [
        pod for pod in rest.pods()
        if str(pod.get("name", "")).startswith(prefix) and pod.get("desiredStatus") != "TERMINATED"
    ]
    if busy:
        names = ", ".join(f"{pod.get('name')} ({pod.get('id')})" for pod in busy)
        raise LoraError(
            f"A training Pod already exists: {names}. End it with `uv run ca lora stop` first."
        )


def start(settings: Settings, chosen: Plan, echo: Echo) -> tuple[TrainRun, RunPodRest, VolumeStore]:
    """Upload, then create the Pod; returns the run record (already saved)."""
    config = load_lora_config(settings.lora_config_file)
    rest, volume_id = _clients(settings)
    _ensure_single(rest, config)
    store = _store(settings, rest, volume_id)
    remote = config.remote
    run_id = f"r{_now():%Y%m%d-%H%M%S}"
    dataset = newest_dataset()
    folder = RUNS_DIR / run_id
    jobs: dict[str, str] = {model: job_name(settings, model) for model in chosen.models}
    run = TrainRun(
        run_id=run_id,
        models=chosen.models,
        jobs=jobs,
        dataset=dataset.stem,
        max_hours=remote.max_hours,
        estimate_usd=chosen.estimate_usd,
        max_usd=chosen.max_usd,
    )
    run.save()
    try:
        created = _upload_and_create(
            settings, run, dataset, folder, store, rest, config, volume_id, echo
        )
    except (LoraError, OSError) as error:  # nothing runs: the run did not start
        run.status = f"failed: {error}"
        run.save()
        raise
    run.pod_id = str(created["id"])
    run.pod_name = f"{remote.name_prefix}-{run_id}"
    run.created_at = _now()
    run.status = "running"
    cost = created.get("adjustedCostPerHr") or created.get("costPerHr")
    run.cost_per_hr = float(cost) if isinstance(cost, int | float) else None
    run.save()
    rate = f"${run.cost_per_hr:.2f}/h" if run.cost_per_hr else "rate not reported"
    echo(f"Pod {run.pod_id} created ({rate}); billing has started. Ctrl+C terminates it.")
    return run, rest, store


def _upload_and_create(
    settings: Settings,
    run: TrainRun,
    dataset: Path,
    folder: Path,
    store: VolumeStore,
    rest: RunPodRest,
    config: LoraConfig,
    volume_id: str,
    echo: Echo,
) -> dict[str, Any]:
    pod, remote, run_id = config.pod, config.remote, run.run_id
    echo(f"Uploading {dataset.name} to the network volume ...")
    with zipfile.ZipFile(dataset) as bundle:
        for name in bundle.namelist():
            if not name.endswith("/"):
                store.put(f"{pod.datasets}/{name}", bundle.read(name))
    for model in run.models:
        path, _ = training_config(settings, model, dataset, out_dir=folder, run_id=run_id)
        store.put(f"lora/runs/{run_id}/{path.name}", path.read_bytes())
    store.put(f"lora/runs/{run_id}/train.sh", TRAIN_SCRIPT.encode("utf-8"))
    limit_s = max(600, int(remote.max_hours * 3600) - _POD_LIMIT_MARGIN_S)
    body = {
        "name": f"{remote.name_prefix}-{run_id}",
        "templateId": remote.template_id,
        "gpuTypeIds": remote.gpu_type_ids,
        "gpuCount": 1,
        "cloudType": remote.cloud_type,
        "networkVolumeId": volume_id,
        "volumeMountPath": pod.pod_volume,
        "containerDiskInGb": remote.container_disk_gb,
        "dockerStartCmd": ["bash", f"{pod.pod_volume}/lora/runs/{run_id}/train.sh"],
        "env": {
            "CA_RUN_ID": run_id,
            "CA_JOBS": " ".join(run.jobs[model] for model in run.models),
            "CA_LIMIT_SECONDS": str(limit_s),
        },
    }
    echo("Creating the Pod ...")
    return rest.create_pod(body)


def _sync_samples(run: TrainRun, store: VolumeStore) -> list[str]:
    """Download new sample images: outputs/lora/<model>/samples/<run>/step_<n>/."""
    new = []
    for model, job in run.jobs.items():
        target = OUT_DIR / model / "samples" / run.run_id
        run.samples[model] = str(target)
        for key in store.keys(f"lora/output/{run.run_id}/{job}/samples/"):
            name = key.rsplit("/", 1)[-1]
            match = _SAMPLE.search(name)
            step = f"step_{int(match.group(1)):06d}" if match else "other"
            path = target / step / name
            if not path.exists():
                store.download(key, path)
                new.append(f"{model} {step}: {path}")
    return new


def _finish(run: TrainRun, store: VolumeStore | None, status: str | None = None) -> None:
    run.ended_at = run.ended_at or _now()
    if store is not None:
        try:
            remote = store.read_text(f"lora/runs/{run.run_id}/status") or run.remote_status
            run.remote_status = remote
            _sync_samples(run, store)
            log = f"lora/runs/{run.run_id}/log.txt"
            if store.read_text(log) is not None:
                store.download(log, run.folder / "log.txt")
            for model, job in run.jobs.items():
                run.checkpoints[model] = sorted(
                    key.rsplit("/", 1)[-1]
                    for key in store.keys(f"models/loras/{run.run_id}_{job}")
                    if key.endswith(".safetensors")
                )
        except LoraError as error:  # the Pod is gone; the files can be fetched later
            run.notes.append(f"Final files not read ({error}); run `uv run ca lora status`.")
    if status is not None:
        run.status = status
    elif run.remote_status.startswith(FINISHED):
        run.status = run.remote_status
    else:
        run.status = "stopped: the Pod ended without a final status (see log.txt)"
    if run.cost_per_hr and run.created_at:
        hours = (run.ended_at - run.created_at).total_seconds() / 3600
        run.actual_usd = round(run.cost_per_hr * hours, 2)
    run.save()


def _terminate(rest: RunPodRest, run: TrainRun) -> None:
    if run.pod_id:
        rest.delete_pod(run.pod_id)


def watch(
    run: TrainRun,
    rest: RunPodRest,
    store: VolumeStore,
    echo: Echo,
    *,
    config: LoraConfig,
    sleep: Callable[[float], None] = time.sleep,
) -> TrainRun:
    """Follow the run until the Pod is gone; terminate it on the limit, Ctrl+C or any error."""
    remote = config.remote
    assert run.created_at is not None
    failures = 0  # polls in a row that could not reach RunPod
    try:
        while True:
            now = _now()
            try:
                pod = rest.pod(run.pod_id or "")
                text = store.read_text(f"lora/runs/{run.run_id}/status") or ""
                new = _sync_samples(run, store)
                failures = 0
            except LoraError as error:
                failures += 1
                if failures >= _MAX_POLL_FAILURES:
                    raise
                echo(f"[{now:%H:%M}] could not check the Pod ({error}); trying again")
                sleep(remote.poll_seconds)
                continue
            state = str(pod.get("desiredStatus", "")) if pod else "TERMINATED"
            if text and text != run.remote_status:
                run.remote_status = text
                echo(f"[{now:%H:%M}] Pod: {text}")
            for line in new:
                echo(f"  new sample: {line}")
            if text.startswith(FINISHED) and run.finished_seen_at is None:
                run.finished_seen_at = now
            run.save()
            if state == "TERMINATED":
                _finish(run, store)
                return run
            if state == "EXITED":  # the start command ended: free the disk too
                _terminate(rest, run)
                _finish(run, store)
                return run
            hours = (now - run.created_at).total_seconds() / 3600
            if hours >= run.max_hours:
                _terminate(rest, run)
                _finish(run, store, f"stopped: hard limit of {run.max_hours:g} h reached")
                return run
            seen = run.finished_seen_at
            if seen is not None and (now - seen).total_seconds() >= remote.finish_grace_seconds:
                _terminate(rest, run)  # it did not terminate itself
                run.notes.append("The Pod did not terminate itself; terminated by this computer.")
                _finish(run, store)
                return run
            sleep(remote.poll_seconds)
    except BaseException as error:  # Ctrl+C or any error: never leave the Pod running
        reason = "Ctrl+C" if isinstance(error, KeyboardInterrupt) else type(error).__name__
        try:
            _terminate(rest, run)
            _finish(run, None, f"stopped: {reason} while watching; the Pod was terminated")
        except Exception:
            run.status = (
                f"stopped: {reason}; terminating the Pod FAILED: end it with `uv run ca lora stop`"
            )
            run.save()
        raise


def result_lines(run: TrainRun) -> list[str]:
    actual = f"${run.actual_usd:.2f}" if run.actual_usd is not None else "unknown"
    lines = [
        f"Run {run.run_id}: {run.status}",
        f"Cost: {actual} actual (Pod rate x time it existed; the RunPod billing page has the "
        f"exact amount); estimate ${run.estimate_usd:.2f}, hard limit ${run.max_usd:.2f}.",
    ]
    lines += [f"Note: {note}" for note in run.notes]
    for model in run.models:
        folder = run.samples.get(model)
        if folder:
            lines.append(f"{model} samples per checkpoint: {Path(folder).resolve()}")
        files = run.checkpoints.get(model, [])
        if files:
            lines.append(f"{model}: pick the checkpoint whose samples look most like him:")
            lines += [f"  uv run ca lora set {model} {name}" for name in files]
        elif run.status.startswith("done"):
            lines.append(f"{model}: no LoRA file found in models/loras/ (see log.txt).")
    if (run.folder / "log.txt").exists():
        lines.append(f"Pod log: {(run.folder / 'log.txt').resolve()}")
    lines.append(f"Record: {(run.folder / RUN_FILE).resolve()}")
    return lines


def status(settings: Settings, echo: Echo) -> TrainRun | None:
    """The latest run: its Pod, the script's status and new samples (finalized when ended)."""
    run = latest_run()
    if run is None:
        echo("No remote training run yet.")
        return None
    if run.status not in ACTIVE or not run.pod_id:
        for line in result_lines(run):
            echo(line)
        return run
    rest, volume_id = _clients(settings)
    store = _store(settings, rest, volume_id)
    pod = rest.pod(run.pod_id)
    state = str(pod.get("desiredStatus", "")) if pod else "TERMINATED"
    run.remote_status = store.read_text(f"lora/runs/{run.run_id}/status") or run.remote_status
    for line in _sync_samples(run, store):
        echo(f"  new sample: {line}")
    if state == "TERMINATED":
        _finish(run, store)
        for line in result_lines(run):
            echo(line)
        return run
    run.save()
    assert run.created_at is not None
    hours = (_now() - run.created_at).total_seconds() / 3600
    cost = f", about ${run.cost_per_hr * hours:.2f} so far" if run.cost_per_hr else ""
    echo(f"Run {run.run_id}: Pod {run.pod_id} {state}, {hours:.2f} h of {run.max_hours:g} h"
         f"{cost}; Pod says: {run.remote_status or 'nothing yet'}")
    for model, folder in run.samples.items():
        echo(f"  {model} samples: {Path(folder).resolve()}")
    return run


def stop(settings: Settings, echo: Echo) -> None:
    """Terminate this tool's Pod(s) now and record the run as stopped."""
    config = load_lora_config(settings.lora_config_file)
    rest, volume_id = _clients(settings)
    ended = []
    run = latest_run()
    if run is not None and run.pod_id and run.status in ACTIVE:
        rest.delete_pod(run.pod_id)
        ended.append(run.pod_id)
        try:
            store: VolumeStore | None = _store(settings, rest, volume_id)
        except LoraError:
            store = None
        _finish(run, store, "stopped: by `ca lora stop`")
    for pod in rest.pods():
        if str(pod.get("name", "")).startswith(config.remote.name_prefix) and (
            pod.get("desiredStatus") != "TERMINATED" and pod.get("id") not in ended
        ):
            rest.delete_pod(str(pod["id"]))
            ended.append(str(pod["id"]))
    echo(f"Terminated: {', '.join(ended)}." if ended else "No training Pod was running.")
    if run is not None and run.pod_id in ended:
        for line in result_lines(run):
            echo(line)
