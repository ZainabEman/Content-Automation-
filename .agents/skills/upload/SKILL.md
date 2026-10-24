---
name: upload
description: Upload Branded Genius files to Google Drive with the Codex Google Drive plugin (STORAGE_PROVIDER=plugin): work through a package's upload_manifest.json (create folders, upload files, the tracker row, the calendar copy) and record the results with `ca drive record <package> --results`; also single upload requests (`ca drive record <jobId>`). Use after a build or a review approval that wrote a manifest, and for "sync drive" and "upload approved files". Free; never uploads what is not in a manifest or request.
---

# Upload

## Rules

- Upload only what `ca` asks for: the approved version's files (`ca item approve` on the review gate writes them; config/storage.json `upload.requireReview`). Never upload other files, never make anything public, never change sharing.
- Plugins are found at run time; never assume tool names. If the Google Drive plugin is missing, stop and name it.
- Never rename, move or delete an existing Drive folder. New category folders are created by the manifest or `ca drive setup`. YouTube topics also use a manifest when `STORAGE_PROVIDER=plugin`: `ca youtube upload BG-x` lists scripts and storyboards (never the local research file), and `ca youtube record BG-x --results <json>` records plugin IDs and queues the tracker CSV.
- Record every upload with `ca`; never say "uploaded" without the file ID and link the plugin returned. Mock uploads stay labelled mock.

## Steps

1. "sync drive" with STORAGE_PROVIDER mock or drive: `uv run ca drive sync` (AGENTS.md → Playbooks → Drive sync).
2. "upload approved files" with STORAGE_PROVIDER=plugin: read every request in `state/uploads/<jobId>.json` (`file`, `folder` such as `Content Automation/Facebook/<Content ID>/v2/`).
3. Per request: `uv run ca jobs check <jobId>`. "skip": it is recorded already; "stop": report and stop; "go": find or make the folder path with the Google Drive plugin, upload the file into it.
4. Right after each upload: `uv run ca drive record <jobId> --file-id <the plugin's file ID> --link <its link>`. A failed upload: say so with the plugin's error; do not record it.
5. Report per item the uploaded files and the "every file uploaded" lines.

## Upload manifest (STORAGE_PROVIDER=plugin)

A finished package (after `ca content build`, `ca calendar generate --build`, or `ca item approve` when config/storage.json `upload.requireReview` is true) has `<package>/upload_manifest.json`; the package status is `upload_pending`. "sync drive" (`uv run ca drive sync`) refreshes every pending manifest and lists them.

1. Do every entry that is not `done`, in order, with the Google Drive plugin (find its tools at run time):
   - `create_folder`: look for a folder `name` inside `parent_folder_id` (from the earlier result when it is null); reuse it if it exists, else create it. Result: `{"id": "<entry id>", "folder_id": "<its ID>"}`.
   - `upload`: upload `local_path` as `target_name` into `target_folder_id` (from the created folder when it is null). A file of that name already in the folder is reused (`replace_existing`: replaced), never added twice. Result: `{"id": "<entry id>", "file_id": "<ID>", "link": "<link>"}`.
   - `sheet_append`: if the plugin can append rows to a Google Sheet, append `rows` to the Sheet `sheet_name` in the folder `parent_folder_id` (create it with `header` first if missing): `{"id": "tracker", "status": "done"}`. If it cannot: `{"id": "tracker", "status": "skipped"}`, then do the `tracker.csv` upload entry (Content Automation/Calendar/). Do `tracker.csv` only after a skip.
   - A failed call: `{"id": "<entry id>", "status": "failed", "error": "<what happened>"}`; no retry without the user's yes.
2. Save the results as a JSON list in `<package>/upload_results.json` and run `uv run ca drive record "<package>" --results "<package>/upload_results.json"`. Recorded entries are skipped on a rerun (no duplicates).
3. When every file is up, it adds the post-upload entries (the tracker row and the calendar copy) and marks the calendar row Generated: do 1-2 again for them. Finished when it prints "(all done)". Report the Drive folder and the files.

## YouTube topic manifest

`ca youtube upload BG-x` writes `upload_manifest.json` in the topic folder when the configured
provider is `plugin`. Follow the same folder and file instructions above. After the script and
storyboard entries are recorded, `ca youtube record BG-x --results <json>` upserts the tracker
row locally and adds a `tracker.csv` upload entry for `Content Automation/Calendar/`. Upload that
entry and call `ca youtube record` again. The YouTube manifest does not upload `research.txt` or
mark a social calendar row Generated.

Never upload a file that is not in the manifest, never make anything public, never change sharing.
