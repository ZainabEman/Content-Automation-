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
        Phrase("retry failed jobs", "ca jobs retry BG-x|--all-failed",
               "a dry run; after ok --authorize; at most max_attempts tries"),
        Phrase("show costs", "ca costs report", "estimate vs actual per job type"),
        Phrase("what can I say", "ca help commands", "this list"),
    )),
    Group("show-content", ".agents/skills/show-content/SKILL.md", (
        Phrase("show content", "Gmail plugin (read-only)", "new ideas from the newsletters"),
        Phrase("show content --all", "Gmail plugin (read-only)", "also emails used before"),
        Phrase("what's new", "Gmail plugin (read-only)", "as show content"),
        Phrase("new ideas from my newsletters", "Gmail plugin (read-only)", "as show content"),
    )),
    Group("research-ideas", ".agents/skills/research-ideas/SKILL.md", (
        Phrase("find new ideas", "ca research run",
               "newsletters and sources become backlog ideas; counts"),
        Phrase("research this link <url>", "ca research fetch <url> [--idea BG-x]",
               "the page's text saved as a source (SRC-####)"),
        Phrase("add topic <text>", 'ca ideas add "<text>"',
               "an idea kept verbatim, deduped, first pillar"),
        Phrase("show backlog", "ca ideas list", "every idea with score, pillar and flags"),
        Phrase("show ideas", "ca ideas list", "as show backlog"),
        Phrase("review ideas", "ca ideas review", "proposed ideas, best first, with sources"),
        Phrase("merge BG-x into BG-y", "ca ideas merge BG-x BG-y",
               "sources move over; BG-x rejected as duplicate"),
        Phrase("show claims for BG-x", "ca claims list BG-x",
               "labelled claims with the status ca decided"),
    )),
    Group("make-calendar", ".agents/skills/make-calendar/SKILL.md", (
        Phrase("make calendar", "ca calendar new --week next", "a proposed week, BG IDs"),
        Phrase("make calendar next week", "ca calendar new --week next", "as make calendar"),
        Phrase("plan next week", "ca calendar plan --week next",
               "slots filled from approved ideas (inherited approval)"),
        Phrase("plan next month", "ca calendar plan --month next",
               "the month's slots into each week's CSV"),
        Phrase("show month", "ca calendar show --month next", "the month's rows of every week"),
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
    Group("write-script", ".agents/skills/write-script/SKILL.md", (
        Phrase("write script for BG-x", "ca script template BG-x --json; ca script save BG-x",
               "a checked, versioned script from the formula and claims"),
        Phrase("write copy for BG-x", "ca script template BG-x --json; ca script save BG-x",
               "post, carousel or ad copy; fills its brief.json fields"),
        Phrase("write brief for BG-x", "ca brief template BG-x --json; ca brief save BG-x",
               "the production brief (YouTube, podcast, social)"),
        Phrase("rewrite script BG-x <feedback>", 'ca item revise BG-x "<feedback>"; then write',
               "a new version; the old one stays"),
        Phrase("show script BG-x", "ca script show BG-x", "the saved script as Markdown"),
        Phrase("check script BG-x", "ca script check BG-x", "the check run again"),
        Phrase("show brief BG-x", "ca brief show BG-x", "the saved production brief"),
    )),
    Group("review-assets", ".agents/skills/review-assets/SKILL.md", (
        Phrase("what needs review", "ca review list", "generated items not reviewed yet"),
        Phrase("show BG-x for review", "ca review show BG-x",
               "version, files, checks, costs, last feedback"),
        Phrase("regenerate BG-x", "ca regenerate BG-x", "a dry run for the parts; ok first"),
        Phrase("redo slide 3 of BG-x", "ca regenerate BG-x --only slide3",
               "only that slide; the others are kept"),
    )),
    Group("produce-video", ".agents/skills/produce-video/SKILL.md", (
        Phrase("production status", "ca production list [--month]",
               "youtube and podcast production; finals vs targets"),
        Phrase("import recording/final for BG-x <path>",
               'ca import BG-x "<path>" --as recording|final', "a checked copy; status moves"),
        Phrase("send BG-x to the editor <name>", 'ca handoff BG-x --to "<name>"',
               "the handoff folder; production editing"),
        Phrase("BG-x recorded", "ca production set BG-x recorded", "only a legal move"),
        Phrase("make thumbnail for BG-x", "ca thumbnail BG-x", "1280x720 with the brief's text"),
        Phrase("export podcast audio for BG-x", "ca podcast audio BG-x", "MP3, -16 LUFS"),
    )),
    Group("clips", ".agents/skills/clips/SKILL.md", (
        Phrase("make clips from BG-x", "ca clips handoff BG-x", "the Opus Pro note (manual)"),
        Phrase("import clips for BG-x <folder>", 'ca clips import BG-x "<folder>"',
               "candidate shorts (vertical, 15-90 s)"),
        Phrase("select clips … for BG-x", "ca clips select BG-x <numbers>",
               "the user's picks approved; the rest not selected"),
    )),
    Group("distribute", ".agents/skills/distribute/SKILL.md", (
        Phrase("prepare BG-x for all platforms", "ca prepare BG-x",
               "variants per platform; copy with ca copy save"),
        Phrase("what's ready to publish", "ca publish list --ready", "ready platforms"),
        Phrase("BG-x is live on LinkedIn <url>",
               "ca publish mark BG-x --platform linkedin --url <url>", "published with its URL"),
        Phrase("BG-x failed on TikTok <reason>",
               'ca publish fail BG-x "<reason>" --platform tiktok', "failed with the reason"),
    )),
    Group("upload", ".agents/skills/upload/SKILL.md", (
        Phrase("upload approved files", "ca drive record <job> --file-id --link",
               "plugin upload requests, each recorded"),
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
