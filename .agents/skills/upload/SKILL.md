---
name: upload
description: Upload approved Branded Genius files to Google Drive. With STORAGE_PROVIDER=plugin, `ca` writes upload requests when a review is approved and this skill uploads each one with the Google Drive plugin, then records it with `ca drive record`. Use for "sync drive" and "upload approved files". Free; never uploads an unapproved version.
---

# Upload

## Rules

- Upload only what `ca` asks for: the approved version's files (`ca item approve` on the review gate writes them; config/storage.json `upload.requireReview`). Never upload other files, never make anything public, never change sharing.
- Plugins are found at run time; never assume tool names. If the Google Drive plugin is missing, stop and name it.
- Record every upload with `ca`; never say "uploaded" without the file ID and link the plugin returned. Mock uploads stay labelled mock.

## Steps

1. "sync drive" with STORAGE_PROVIDER mock or drive: `uv run ca drive sync` (AGENTS.md → Playbooks → Drive sync).
2. "upload approved files" with STORAGE_PROVIDER=plugin: read every request in `state/uploads/<jobId>.json` (`file`, `folder` such as `Content Automation/Facebook/<Content ID>/v2/`).
3. Per request: `uv run ca jobs check <jobId>`. "skip": it is recorded already; "stop": report and stop; "go": find or make the folder path with the Google Drive plugin, upload the file into it.
4. Right after each upload: `uv run ca drive record <jobId> --file-id <the plugin's file ID> --link <its link>`. A failed upload: say so with the plugin's error; do not record it.
5. Report per item the uploaded files and the "every file uploaded" lines.
