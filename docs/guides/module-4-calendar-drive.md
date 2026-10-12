# Module guide: Calendar, Google Drive and the Content Tracker

## What it does

Codex plans a week of posts, waits for your approval, makes only the approved ones, uploads the
finished images and videos to Google Drive and lists every finished post in the **Content
Tracker** (a Google Sheet) for the social media manager. Nothing is posted automatically.

## One-time setup

Drive and the tracker need a one-time Google setup: [Set up Codex, section 9](../SETUP-CODEX.md#9-google-drive-and-the-content-tracker-optional)
(Drive API + Sheets API, the client JSON in `.secrets/`, `uv run ca drive setup`,
`STORAGE_PROVIDER=drive`, optionally `DRIVE_SHARE_WITH`). Until then everything still works and
goes to `outputs/drive/` on this computer.

## What to type in Codex

| You type | What happens |
| --- | --- |
| "make calendar" / "make calendar next week" | Codex picks ideas (your newsletters, the news, your own topics) and proposes the week: Mon LinkedIn, Tue Facebook, Wed LinkedIn, Thu Facebook, Fri Instagram carousel (`config/calendar.json`). Every row starts as Proposed. Free. |
| "approve all" / "approve 1 3 5" / "reject 2" | Rows become Approved or Rejected (you can change your mind; a Generated row stays as it is). Free. |
| "make an insta post about TOPIC" | An animated Instagram carousel (8 slides, 5 s each, no people): texts first, then ONE dry run with the Higgsfield credits per slide (still + clip), the total, the most it can cost with retries and the $ value. Nothing is spent. |
| "generate approved" | One package per approved row, texts written, then ONE dry run: the cost per row and the total ($, and credits for carousels), and any LinkedIn post without you ("no person"). Nothing is spent. |
| "ok" | Makes the approved rows (paid). Images with you stop for the usual person check. A carousel runs to the end without more questions (stops only if it would cost more than the maximum you approved). Each finished post is uploaded to Drive and added to the tracker; its calendar row becomes Generated. |
| "continue carousel <folder>" | A carousel that was interrupted carries on where it stopped; nothing already made is paid for again. |
| "sync drive" | Uploads what is still missing (failed uploads are tried again), refreshes the calendar copy and updates the tracker. A file is never uploaded twice. |
| "show tracker" | How many posts are Pending, Approved, Rejected and Posted. |

## Where things are

- `calendar/2026-W42.csv`: the week's plan; a read-only copy is in Drive `Content Automation/Calendar/`.
- Drive `Content Automation/LinkedIn|Facebook|Instagram/<Content ID>/` (e.g. `2026-W42-03`): the images and videos of one post. A carousel's folder holds `slide_01..08.mp4` (to post), `slide_01..08.png` (still versions), `caption.txt` (caption and hashtags to paste) and `originals/` (the pictures without text).
- **Content Tracker** in `Content Automation/`: one row per finished post with Content ID, Topic,
  Research source, Platform, Content type, Caption, Hashtags and the link to the post's folder.

## The manager's routine

1. Open the Content Tracker. New rows have Approval status **Pending** and Publishing status **Pending**.
2. Review: open the Image/video link, read the Caption and Hashtags, then set Approval status to
   **Approved** or **Rejected**. A Facebook ad has three "— Version N —" blocks in its caption; each names its image.
   A carousel's caption may end with "Notes:" (a slide made with the simpler local animation, or a
   slide whose colours differ from the others): check those slides before approving.
3. Publish by hand on the platform (copy the caption and hashtags, download the image or video).
4. Set Publishing status to **Posted** and fill in the Publication date (date picker).

The app never changes these three columns and never deletes a row. You may sort, filter, format
and add columns; keep the header names in row 1. Edit only the Sheet: "Content Tracker.csv"
("export tracker") is a read-only copy.

## Troubleshooting

| Message | What to do |
| --- | --- |
| "Drive not set up — run ca drive setup" | Do the one-time setup; the files stay on this computer meanwhile. |
| "Tracker waits for …: upload failed" | Say "sync drive" later; the row is added once every file is uploaded. |
| "Content Tracker: row 1 has no … column" | Put that header name back in row 1, then "sync drive". |
| "Google HTTP 403 … Sheets API" | Enable the Google Sheets API in Google Cloud, then "sync drive". |
| Asked to sign in again after 7 days | The Google app is in testing mode: publish it (section 9, step 5) and run `uv run ca drive setup`. |
