"""Typer command line interface."""

import typer

from content_automation.core.config import ConfigurationError, load_settings

app = typer.Typer(name="ca", no_args_is_help=True, help="Content Automation CLI.")


@app.callback()
def _root() -> None:
    """Root command for the Content Automation CLI."""


@app.command()
def hello() -> None:
    """Show a safe summary of the local configuration."""
    try:
        settings = load_settings()
    except ConfigurationError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None

    typer.echo(f"Hello, {settings.user_name}.")
    typer.echo("Configuration summary (credential values hidden):")
    for line in settings.summary_lines():
        typer.echo(f"  {line}")
