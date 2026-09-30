"""CLI entry point: python -m imagegen generate ..."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import bfl, storage
from .config import MAX_OUTPUT_PIXELS, MAX_REQUEST_PIXELS, MAX_REFERENCE_IMAGES, load_config
from .models import ImageGenerationJob
from .references import PreparedReferenceSet, load_reference_set

ASPECT_SIZES = {
    "1:1": (1024, 1024),
    "4:5": (1024, 1280),
    "9:16": (720, 1280),
    "16:9": (1280, 720),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m imagegen")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="Generate one FLUX.2 Pro image.")
    generate.add_argument("--prompt", required=True, help="Describe the scene to generate.")
    generate.add_argument("--reference-set", help="Identity-reference folder name, for example person_01.")
    generate.add_argument("--aspect-ratio", choices=tuple(ASPECT_SIZES), default="1:1")
    generate.add_argument("--output-format", choices=("jpeg", "png"), default="jpeg")
    generate.add_argument("--seed", type=int)
    generate.add_argument("--dry-run", action="store_true", help="Validate and summarize without calling BFL.")
    return parser


def _build_final_prompt(user_prompt: str, reference_count: int) -> str:
    if reference_count:
        numbers = ", ".join(f"image {index}" for index in range(1, reference_count + 1))
        identity_instruction = (
            f"Use the same person shown in {numbers}. Preserve their face and identity unchanged. "
        )
        return identity_instruction + user_prompt.strip()
    return user_prompt.strip()


def _build_payload(
    final_prompt: str,
    aspect_ratio: str,
    output_format: str,
    seed: int | None,
    references: PreparedReferenceSet | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    width, height = ASPECT_SIZES[aspect_ratio]
    output_pixels = width * height
    if output_pixels > MAX_OUTPUT_PIXELS:
        raise ValueError(f"Selected output size exceeds BFL's {MAX_OUTPUT_PIXELS:,}-pixel output limit.")
    parameters: dict[str, Any] = {
        "aspect_ratio": aspect_ratio,
        "width": width,
        "height": height,
        "output_format": output_format,
    }
    payload: dict[str, Any] = {"prompt": final_prompt, "width": width, "height": height, "output_format": output_format}
    if seed is not None:
        payload["seed"] = seed
        parameters["seed"] = seed
    if references:
        if len(references.references) > MAX_REFERENCE_IMAGES:
            raise ValueError(f"FLUX.2 Pro accepts at most {MAX_REFERENCE_IMAGES} API reference images.")
        if references.total_pixels + output_pixels > MAX_REQUEST_PIXELS:
            raise ValueError("Reference images and output exceed BFL's documented 9MP request budget.")
        for index, reference in enumerate(references.references, start=1):
            field = "input_image" if index == 1 else f"input_image_{index}"
            payload[field] = reference.image_base64
        parameters["reference_count"] = len(references.references)
        parameters["reference_pixels"] = references.total_pixels
    return payload, parameters


def _new_job(
    user_prompt: str,
    final_prompt: str,
    endpoint: str,
    parameters: dict[str, Any],
    references: PreparedReferenceSet | None,
) -> ImageGenerationJob:
    now = storage.utc_now()
    reference_files = [reference.metadata() for reference in references.references] if references else []
    return ImageGenerationJob(
        job_id=storage.new_id("job"),
        workflow_id="person_lifestyle",
        provider="bfl",
        provider_job_id=None,
        prompt=final_prompt,
        user_prompt=user_prompt.strip(),
        final_prompt=final_prompt,
        reference_asset_ids=[],
        product_asset_ids=[],
        brand_reference_asset_ids=[],
        reference_files_used=[{"name": item["name"], "sha256": item["sha256"]} for item in reference_files],
        parameters={**parameters, "endpoint": endpoint},
        status="queued",
        output_asset_ids=[],
        output_asset_paths=[],
        output_assets=[],
        error=None,
        created_at=now,
        updated_at=now,
    )


def _record_failure(job: ImageGenerationJob, message: str) -> None:
    job.status = "failed"
    job.error = {"message": message}
    job.updated_at = storage.utc_now()
    storage.save_job(job)


def _dry_run_summary(
    references: PreparedReferenceSet | None,
    parameters: dict[str, Any],
    endpoint: str,
) -> str:
    output_pixels = parameters["width"] * parameters["height"]
    lines = [
        "DRY RUN — no API call was made",
        f"Endpoint: {endpoint}",
        f"Output: {parameters['width']}x{parameters['height']} ({parameters['aspect_ratio']}); {parameters['output_format']}",
        f"Output pixels: {output_pixels:,} (BFL maximum {MAX_OUTPUT_PIXELS:,})",
    ]
    if references:
        lines.extend(
            [
                f"Reference set: {references.name}",
                f"References: {len(references.references)}/{MAX_REFERENCE_IMAGES}; source files: {references.source_count}; omitted: {references.omitted_count}",
                f"Reference pixels after resize: {references.total_pixels:,}; combined with output: {references.total_pixels + output_pixels:,}/{MAX_REQUEST_PIXELS:,}",
                "Files: " + ", ".join(reference.source_path.name for reference in references.references),
            ]
        )
    else:
        lines.append("References: none")
    return "\n".join(lines)


def run_generate(args: argparse.Namespace) -> int:
    try:
        user_prompt = args.prompt.strip()
        if not user_prompt:
            raise ValueError("--prompt cannot be empty.")
        width, height = ASPECT_SIZES[args.aspect_ratio]
        references = (
            load_reference_set(args.reference_set, output_pixels=width * height)
            if args.reference_set
            else None
        )
        final_prompt = _build_final_prompt(user_prompt, len(references.references) if references else 0)
        payload, parameters = _build_payload(final_prompt, args.aspect_ratio, args.output_format, args.seed, references)
        config = load_config(require_key=False)
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "failed", "job_id": None, "image_path": None, "error": str(exc)}), flush=True)
        return 2

    if args.dry_run:
        print(_dry_run_summary(references, parameters, config.endpoint), file=sys.stderr, flush=True)
        print(json.dumps({"status": "dry_run", "job_id": None, "image_path": None}), flush=True)
        return 0

    job = _new_job(user_prompt, final_prompt, config.endpoint, parameters, references)
    storage.save_job(job)
    if not config.api_key:
        message = "BFL_API_KEY is missing. Add it to the project .env file before running a real generation."
        _record_failure(job, message)
        print(json.dumps({"status": job.status, "job_id": job.job_id, "image_path": None, "error": message}), flush=True)
        return 1

    try:
        result = bfl.submit_poll_download(
            payload,
            config,
            on_submitted=lambda provider_job_id: _on_submitted(job, provider_job_id),
            on_processing=lambda: _on_processing(job),
        )
        asset, relative_image_path, full_image_path = storage.save_image(result.image_bytes, args.output_format)
        job.output_asset_ids = [asset.asset_id]
        job.output_asset_paths = [relative_image_path]
        job.output_assets = [asset.to_dict()]
        job.status = "completed"
        job.error = None
        job.updated_at = storage.utc_now()
        storage.save_job(job)
        print(json.dumps({"status": "completed", "job_id": job.job_id, "image_path": full_image_path}), flush=True)
        return 0
    except (bfl.ProviderError, ValueError) as exc:
        _record_failure(job, str(exc))
        print(json.dumps({"status": "failed", "job_id": job.job_id, "image_path": None, "error": str(exc)}), flush=True)
        return 1


def _on_submitted(job: ImageGenerationJob, provider_job_id: str) -> None:
    job.provider_job_id = provider_job_id
    job.status = "processing"
    job.updated_at = storage.utc_now()
    storage.save_job(job)


def _on_processing(job: ImageGenerationJob) -> None:
    if job.status != "processing":
        job.status = "processing"
        job.updated_at = storage.utc_now()
        storage.save_job(job)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return run_generate(args)


if __name__ == "__main__":
    raise SystemExit(main())

