# Content Automation v2 – PRD

## Rules (apply to every phase)

- Codex Desktop stays the main controller; all user commands are typed in Codex.
- Inspect the current automation before changing it. Preserve existing research, copywriting, approval, cost-approval and folder logic wherever possible.
- No paid generation without an approved cost estimate shown to the user first.
- Keep the existing image method (Nano Banana 2 via OpenRouter) available until its replacement passes Phase 4 tests.
- No automatic publishing in v1.

## Phases

- Phase 1: content calendar + approval; LinkedIn added as a platform; Google Drive folders + tracking CSV (uses current image generation).
- Phase 2: ComfyUI connection to Codex + ComfyUI image generation for LinkedIn and Facebook.
- Phase 3: Instagram animated carousel via Higgsfield.
- Phase 4: all testing.

## 1. Content calendar and approval

- Keep both research branches: Gmail newsletters (label "Newsletters") and user-provided topics.
- Generate a proposed content calendar from the collected research. Each row: planned date, topic, research source, planned platform (LinkedIn / Facebook / Instagram), content type.
- Save the calendar and wait for the social media manager's approval (whole calendar or selected rows).
- Generate content for LinkedIn, Facebook and Instagram only for approved rows.

## 2. LinkedIn and Facebook image generation (Phase 2)

- Replace Nano Banana 2/OpenRouter with a ComfyUI workflow.
- Use the 9 photos of Roman as identity references.
- Choose base model + identity method (LoRA if suitable) after checking image quality, commercial licence and hardware needs.
- Roman's accurate, recognizable appearance is the priority, especially in Facebook ads.
- LinkedIn posts may use images without Roman when appropriate.
- Content-writing and research branches stay unchanged.
- Official logo is composited as a separate asset after generation.
- Compare generated images with Roman's reference photos; retry failed results.
- Nano Banana stays as fallback until the new workflow passes testing.

## 3. ComfyUI connection to Codex (Phase 2)

- Inspect the project and set up the integration.
- Prefer a direct ComfyUI API connection via script or a suitable existing integration. Use MCP/plugin only if genuinely needed.
- Choose local vs cloud after checking hardware, setup complexity and total cost.
- Confirm the model's commercial licence before production use.
- No paid generation without an approved cost estimate.

## 4. Instagram animated carousel (Phase 3)

- Use the existing Higgsfield plugin in Codex.
- Consistent design: matching backgrounds, logo placement, typography, text areas.
- One MP4 per slide, ~4–5 s each. Animate selected elements; text and branding stay readable.
- Save slides in sequence with their original images when available.
- One caption + hashtags for the whole carousel.
- Verify real plugin capabilities and credits before fixing settings. Estimate cost from a small test batch before scaling; do not assume the subscription covers unlimited automated generation.

## 5. Google Drive folders and tracking CSV

- Separate output folders: LinkedIn, Facebook, Instagram (inside one main content folder).
- Upload generated images and MP4s to the matching folder.
- One CSV in the main content folder. Columns: Content ID, Topic, Research source, Platform, Content type, Caption, Hashtags, Image/video link, Approval status, Publishing status, Publication date.
- Approval status: Pending / Approved / Rejected. Publishing status: Pending / Posted.
- The workflow fills the CSV with generated content and file links. The social media manager reviews, publishes manually, then updates status and publication date. The workflow must never overwrite those manual edits.
- **Deviation (to confirm with the client):** the tracking file is a Google Sheet ("Content Tracker") that the app reads and updates cell by cell with the Sheets API, with a CSV export option (`ca tracking export`). Reason: a CSV opened with Google Sheets becomes a separate Sheet, so the manager's edits would never reach the CSV.

## 6. Implementation and testing (Phase 4)

- Test ComfyUI identity consistency and Higgsfield carousel separately.
- Verify Drive uploads, working links, CSV updates and failure handling.
