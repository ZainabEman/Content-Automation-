"""`ca help commands` ("what can I say"): every phrase the user can type in Codex, grouped by
skill, with the command and effect behind it. The same phrases are listed in AGENTS.md (a test
keeps both in step)."""

import json
import sys
from dataclasses import asdict, dataclass
from typing import Annotated

import typer

help_app = typer.Typer(no_args_is_help=True, help="What you can say in Codex.")


@dataclass(frozen=True)
class Phrase:
    phrase: str
    command: str
    effect: str


@dataclass(frozen=True)
class Group:
    skill: str
    path: str
    phrases: tuple[Phrase, ...]


GROUPS: tuple[Group, ...] = (
    Group("manage-items", ".agents/skills/manage-items/SKILL.md", (
        Phrase("show items", "ca item list", "items with their BG ID, statuses and version"),
        Phrase("what's pending", "ca item list --status idea=proposed",
               "ideas to decide, then generated items to review"),
        Phrase("status BG-x", "ca item status BG-x",
               "statuses, versions, decisions, jobs, files and next actions"),
        Phrase("approve BG-x [BG-y]", "ca item approve BG-x [BG-y]",
               "approves the open gate (idea first, then review)"),
        Phrase("reject BG-x <reason>", 'ca item reject BG-x "<reason>"', "reason required"),
        Phrase("revise BG-x <feedback>", 'ca item revise BG-x "<feedback>" [--title]',
               "a new version that must be approved again"),
        Phrase("resubmit BG-x", 'ca item resubmit BG-x --title "<new topic>"',
               "proposes the idea again after a revise without a title"),
        Phrase("history of BG-x", "ca item history BG-x", "every event of the item"),
        Phrase("show audit log", "ca audit show", "the newest events (append-only log)"),
        Phrase("what failed", "ca jobs list --failed", "failed or cancelled jobs"),
        Phrase("unfinished jobs", "ca jobs list --unfinished", "queued or running (stale) jobs"),
        Phrase("resume unfinished jobs", "ca jobs resume [BG-x]",
               "the carousel's next step; other types are not resumable yet"),
        Phrase("show authorizations", "ca auth list", "what each \"ok\" allows: spent of max"),
        Phrase("tracker conflicts", "ca tracking conflicts",
               "hand edits, missing rows, duplicate IDs; then ca tracking resolve"),
        Phrase("what can I say", "ca help commands", "this list"),
    )),
    Group("show-content", ".agents/skills/show-content/SKILL.md", (
        Phrase("show content", "Gmail plugin (read-only)", "new ideas from the newsletters"),
        Phrase("show content --all", "Gmail plugin (read-only)", "also emails used before"),
        Phrase("what's new", "Gmail plugin (read-only)", "as show content"),
        Phrase("new ideas from my newsletters", "Gmail plugin (read-only)", "as show content"),
    )),
    Group("make-calendar", ".agents/skills/make-calendar/SKILL.md", (
        Phrase("make calendar", "ca calendar new --week next", "a proposed week, BG IDs"),
        Phrase("make calendar next week", "ca calendar new --week next", "as make calendar"),
        Phrase("approve all", "ca calendar approve all --week <week>", "every proposed row"),
        Phrase("approve 1 3 5", "ca calendar approve 1 3 5 --week <week>", "those rows"),
        Phrase("reject 2", 'ca calendar reject 2 --week <week> --reason "<reason>"',
               "that row (asks for the reason)"),
        Phrase("generate approved", "ca calendar generate --week <week>",
               "stage 1, then one combined dry run with its dry run ID"),
        Phrase("ok", "... --build --authorize <dryrun_id>",
               "the only spending approval: builds what that dry run showed"),
    )),
    Group("make-content", ".agents/skills/make-content/SKILL.md", (
        Phrase("make 3", 'ca content start --research-file <list> --idea 3 --request "…"',
               "a package from idea 3 (BG IDs once deliverables are named)"),
        Phrase("make 2 and 5", "ca content start ... --idea 2, --idea 5", "one package each"),
        Phrase("make a post about X", 'ca content start --topic "X"', "a package about X"),
        Phrase("make an insta post / facebook ad / reel about X",
               'ca content start --topic "X" --deliverables "…"',
               "a package with those deliverables"),
    )),
    Group("make-carousel", ".agents/skills/make-carousel/SKILL.md", (
        Phrase("continue carousel <folder>", 'ca carousel continue "<folder>"',
               "where the carousel stopped and the next step"),
    )),
    Group("Playbooks (AGENTS.md)", "AGENTS.md", (
        Phrase("sync drive", "ca drive sync", "uploads finished files and the tracker rows"),
        Phrase("show tracker", "ca tracking show", "tracker rows and status counts"),
        Phrase("export tracker", "ca tracking export", "the tracker as CSV"),
        Phrase("train lora", "ca lora train-remote --model both", "parked (LoRA track)"),
    )),
)


def help_lines() -> list[str]:
    lines = []
    for group in GROUPS:
        lines.append(f"{group.skill} ({group.path}):")
        lines += [f'  "{p.phrase}" -> {p.command}: {p.effect}' for p in group.phrases]
    lines.append("Every item has a BG ID; a BG ID, Content ID or row number (with the week) "
                 "works wherever an item is named.")
    return lines


@help_app.command("commands")
def help_commands(
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Every phrase you can say in Codex, grouped by skill ("what can I say")."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    if as_json:
        typer.echo(json.dumps([asdict(group) for group in GROUPS], ensure_ascii=False))
        return
    for line in help_lines():
        typer.echo(line)
