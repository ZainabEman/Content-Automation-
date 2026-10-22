"""`ca image import` (v5b): Codex's built-in images back into the pipeline.

The build writes one job per non-Roman image (outputs/codex_jobs/<batch>/<job>/job.json; provider
codex_builtin). Codex generates each image once and saves it to the job's output_path (skill
generate-images-codex); `ca image import` checks every file (it exists and is an image), marks
its job done and continues each package's build (crop, design, design check, package, Drive,
tracker) with `ca content build`. A missing image keeps its item pending. `ca jobs resume`
re-imports the same way; nothing here generates an image or calls a provider."""

from pathlib import Path
from typing import Annotated

import typer

from content_automation.ai.image import ImageError
from content_automation.ai.image.codex import (
    CodexBuiltinProvider,
    Imported,
    import_images,
)
from content_automation.cli.jobs import _fail, _settings
from content_automation.core.config import Settings

image_app = typer.Typer(
    help="Generate images (options below; no subcommand) or import Codex's images.")


def import_lines(found: Imported) -> list[str]:
    lines = [f"Imported {len(found.imported)} Codex image(s)."]
    lines += [f"- {problem}" for problem in found.problems]
    if found.missing:
        lines.append(f"{len(found.missing)} image(s) missing (their items stay pending; nothing "
                     "is generated here):")
        lines += [f"- {job.batch}/{job.folder.name}: {job.output}" for job in found.missing]
    return lines


def continue_builds(packages: list[Path]) -> None:
    """Each package's build with the imported images (the existing `ca content build`)."""
    from content_automation.cli import content_build

    for folder in packages:
        typer.echo(f"Continue: {folder}")
        try:
            content_build(folder=folder, dry_run=False, authorize_id=None, provider=None)
        except typer.Exit as stopped:
            if stopped.exit_code:
                typer.echo(f"{folder}: the build stopped (exit {stopped.exit_code}).")


def import_and_continue(settings: Settings, batch: str | None = None,
                        keys: set[str] | None = None) -> None:
    root = CodexBuiltinProvider(settings).root()
    try:
        found = import_images(root, batch, keys=keys)
    except ImageError as error:
        _fail(str(error), 2)
    for line in import_lines(found):
        typer.echo(line)
    continue_builds(found.packages)


@image_app.command("import")
def image_import(
    batch: Annotated[
        str | None, typer.Argument(help="The batch (B-…, the folder above each job.json).")
    ] = None,
    every: Annotated[bool, typer.Option("--all", help="Every batch.")] = False,
) -> None:
    """Import Codex's images ("import images"): check each file, mark its job done and continue
    the build (crop, design, check, package, Drive, tracker). A missing image stays pending."""
    if (batch is None) != every:
        _fail("Name one batch or use --all: uv run ca image import B-… | --all", 2)
    import_and_continue(_settings(), batch)
