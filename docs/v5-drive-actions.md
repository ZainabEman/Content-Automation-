# v5: Drive and Sheet actions waiting for Roman's "ok"

Nothing below has been run. No Google call was made in the v5 build (2026-10-19). Each block
runs only after Roman replies "ok" in a later session, and only that block. Nothing in Drive is
deleted, renamed or moved before then. The Drive restructuring spec is still PENDING (PRD R10.3),
so **no existing folder is renamed or moved**, only new folders are created.

Setup on this machine (from `.env`, names only): `STORAGE_PROVIDER=drive`. Drive state and
folder IDs: `.secrets/drive_state.json`; plugin mode IDs: `config/drive_folders.json`
(root, LinkedIn, Instagram, Facebook, YouTube, Calendar).

## 1. Create the new folders (R10.2)

| Folder | Under | Exists today? | How |
|---|---|---|---|
| `Instagram Carousels` | `Content Automation/` | no (new in v5) | `uv run ca drive setup` |
| `Facebook Posts` | `Content Automation/` | no (new in v5) | `uv run ca drive setup` |
| `Facebook Ads` | `Content Automation/` | UNKNOWN (in the folder list since Phase 7; created if missing) | `uv run ca drive setup` |
| `LinkedIn` | `Content Automation/` | yes (`config/drive_folders.json`) | kept as it is |
| `YouTube` | `Content Automation/` | yes (`config/drive_folders.json`) | kept as it is |
| `YouTube/<YYYY-MM>/<BG-ID>_<slug>/` (+ one subfolder per style) | `YouTube/` | no | made by the first `uv run ca youtube upload BG-x` of that topic |

- Command: `uv run ca drive setup` (free; one browser sign-in only if the token expired). It finds
  folders by name and creates only the missing ones; it never renames, moves or deletes.
- Expected output: `Drive is set up: Content Automation/{…,Instagram Carousels,Facebook Posts}
  + Content Tracker`.
- Until setup has run once, `ca drive sync` says "Drive not set up — run ca drive setup" for v5
  packages (their files stay local; nothing is lost).
- Plugin mode only (`STORAGE_PROVIDER=plugin`): add the two new folder IDs to
  `config/drive_folders.json` after they exist (`"Instagram Carousels": "<id>"`,
  `"Facebook Posts": "<id>"`); until then each package's `upload_manifest.json` asks the Drive
  plugin to create them.

## 2. Tracker headers (R11)

Sheet "Content Tracker" (found by name; `.secrets/drive_state.json tracker_id`). Five header
cells are appended **after the last existing column**, matched by header name later (a column
moved by the manager is still found):

`Category` · `Language` · `Layout Variant` · `Requires Roman` · `Selected Script Style`

- How: the next `uv run ca drive sync` (or the first `uv run ca youtube upload BG-x`) writes them
  as part of the normal upsert. No column is reordered; manager columns (Approval status,
  Publishing status, Publication date and any extra columns) are never written for existing rows.
- Values: Category = Instagram Carousel / Facebook Post / Facebook Ad / LinkedIn / YouTube;
  Language = de; Layout Variant = e.g. LI-2; Requires Roman = yes/no; Selected Script Style =
  A/B/C for YouTube rows, "—" otherwise. YouTube rows: one per topic, Content ID = BG ID, the
  Caption cell lists the links to the research file, the six scripts and the storyboard.

## 3. Move the UGC ad folder to the Drive trash (R8.4)

Its exact name and place are **UNKNOWN** (the brief says a UGC ad folder exists; nothing in the
repo or `config/drive_folders.json` names it). The app's Google scope is `drive.file`, so it can
only see files it created itself: a folder made by hand is invisible to `ca`. Steps:

1. **List first (read-only):** with the Google Drive plugin (brandedgenius.de@gmail.com), search
   inside `Content Automation/` for folders whose name contains "UGC" (also "ugc", "UGC Ads",
   "UGC-Ads"). For each match show: full path, folder ID, owner, created and modified dates, and
   the list of files inside (name, type, size, modified). Do not open or change anything.
2. Show that list to Roman and stop. Proceed only after Roman's explicit "ok" naming the folder.
3. **Move to trash (not a permanent delete):** set `trashed: true` on that one folder (Drive
   plugin "move to trash", or Roman does it in the Drive web UI). It stays restorable from the
   Drive trash for 30 days (Google's default).
4. Keep everything else: old UGC rows in the Content Tracker and any UGC files outside that
   folder stay (R8.5); no tracker row is deleted.
5. Record the action in `docs/v5-implementation-notes.md` (folder name, ID, file count, date).

## Not to do (until the PENDING Drive spec arrives)

- No renaming of `Facebook` → `Facebook Posts`, `Instagram` → `Instagram Carousels` or any other
  folder; no moving of existing content folders into the new ones. Old packages keep uploading
  to their old platform folder; v5 packages go to the new category folders.
