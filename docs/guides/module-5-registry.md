# Module guide: content items, approvals and spending (the registry)

## What it does

Every piece of content gets one ID, like **BG-007**, and one record: its idea, sources, versions,
five separate statuses (idea, generation, review, upload, publication), the jobs that made it, what
they cost and everything that happened to it. You approve, reject and revise by that ID in Codex.
Nothing that costs money runs without a dry run you said "ok" to.

## What was built

- A local database `state/registry.db` (never in Git) with the items, versions, decisions, jobs,
  authorizations and an append-only audit log. A backup is made before every upgrade or migration.
- `ca item …` commands and the **manage-items** skill: list, status, approve, reject, revise,
  resubmit, history.
- Dry runs are saved with an ID (`DR-…`). After your "ok", Codex builds with `--authorize <ID>`:
  that creates the spending limit (per provider: dollars or credits). A job only starts if it fits.
- Jobs remember their inputs: running the same thing again reuses the earlier result instead of
  paying twice. A deliberate redo (a failed person check, a carousel retry) is a new job.
- The calendar CSV is now a view of the registry (BG ID, Status, Version columns). If you edit it
  by hand, the next calendar command stops and shows your edits; you choose to keep or drop them.
- The Content Tracker gets BG ID and status columns. Cells the workflow wrote are remembered; if
  someone edits one by hand, that row is not overwritten and shows up in "tracker conflicts".
- `ca registry migrate` registers calendars and packages made before the registry (once).

## One-time setup

Run once, after updating: `uv run ca registry migrate --dry-run` (shows what it would register),
then `uv run ca registry migrate`. Running it again changes nothing. To start the BG numbers at a
client-chosen number, set `"next_id"` in `config/registry.json` before the first item is made.

## How to use

### Example Codex requests

- "show items", "what's pending", "status BG-007", "history of BG-007"
- "approve BG-007 BG-008", "reject BG-009 too generic"
- "revise BG-010 focus on the Mittelstand" (Codex rewrites the topic, shows it and passes it)
- "what failed", "unfinished jobs", "resume unfinished jobs", "show authorizations"
- "tracker conflicts", "show audit log", "what can I say"

## Commands

| Command | What it does |
| --- | --- |
| `uv run ca item list [--status idea=proposed] [--kind] [--week next] [--json]` | Items with their statuses and version. |
| `uv run ca item status BG-007 [--json]` | Everything about one item, mismatches, next allowed actions. |
| `uv run ca item approve\|reject\|revise\|resubmit\|history …` | Decisions by ID (reject needs a reason, revise needs feedback). |
| `uv run ca audit show [--since] [--type] [--item] [--limit 50]` | The audit log (newest last). |
| `uv run ca jobs list [--unfinished\|--failed] \| check <id> \| resume [BG-x] \| cancel <id> "<why>"` | Jobs; `check` is what the plugin skills run before each plugin call. |
| `uv run ca auth list [--open]` | What each "ok" allows and what was spent. |
| `uv run ca calendar sync --week W [--discard-edits\|--import-edits]` | Rewrites the calendar from the registry; settles hand edits. |
| `uv run ca tracking conflicts` / `uv run ca tracking resolve <ID> --keep-sheet\|--use-registry` | Tracker hand edits and missing rows; settle one row. |
| `uv run ca registry migrate [--dry-run]` | Registers older calendars and packages (backup first). |
| `uv run ca help commands` | Every phrase you can say in Codex. |

## Outputs

`state/registry.db`, `state/backups/`, `state/dryruns/DR-….json`. The calendar CSV gains the BG ID,
Status and Version columns; the tracker gains the registry columns at the end.

## Settings

`STATE_DIR` (default `state`), `config/registry.json` (`next_id`), `config/jobs.json` (free
providers, units, timeouts, the credit estimates of video scenes, dry-run expiry),
`config/tracker.json` (the tracker column names; client to confirm).

## Costs and limits

The registry itself is free. It never raises a limit by itself: when a job would go over what an
"ok" allowed, it stops and asks for a new dry run and "ok".

## Troubleshooting

- "Not authorized": run the dry run again, show the cost, and after "ok" build with
  `--authorize <ID>`.
- "Dry run … expired / already used / items changed / costs changed": run a new dry run.
- "edited by hand since the last write": choose `--discard-edits` or `--import-edits`.
- A job marked **stale**: it started but never came back. Check the plugin; only then
  `ca jobs cancel <id> "<why>"` and try again.

## Switching providers

Paid or free is set per provider in `config/jobs.json` (`free_providers`); mock providers are free.
