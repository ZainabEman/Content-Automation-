# Set up Codex Desktop for Content Automation

> **v5 (2026-10-19):** UGC ads, podcast media and finished YouTube videos are no longer generated (PRD v5 R8). Only reels (`reel_short`, Higgsfield) remain as video; HeyGen avatar clips are not used by any workflow. YouTube is research and production planning: `ca youtube` and the make-youtube skill. Everything the audience sees is German.

Follow these steps once per computer. You do not need to know how to code: Codex runs the
commands for you. Each step says what to click or type.

## 1. Install the Codex app (Windows)

1. Install the **ChatGPT desktop app for Windows** from the Microsoft Store:
   <https://get.microsoft.com/installer/download/9PLM9XGG6VKS?cid=website_cta_psi>
   (or, in PowerShell: `winget install --id 9PLM9XGG6VKS -s msstore`).
2. Open it and sign in with your ChatGPT account, then choose **Codex**.
3. Open **Settings** and, under the agent environment, choose **Windows native** (this project
   runs directly on Windows).

Official instructions: <https://learn.chatgpt.com/docs/windows/windows-app>

## 2. Open this folder as a project

1. In Codex, click **Add new project** (or press **Ctrl+O**).
2. Choose the project folder (the one that contains `AGENTS.md` and the `docs` folder).
3. Under the message box, keep **Ask for approval** selected. Codex then asks before running
   anything outside the project's safe limits.

Codex reads `AGENTS.md` automatically: its "Start here (Codex)" section tells Codex how to make
posts, ads and reels.

## 3. Allow internet access for commands

Several commands need the internet: installing the tools (`uv sync`), reading news sites,
and making images with OpenRouter (only when opted in). By default Codex runs commands without internet. To allow
it, edit Codex's settings file:

1. Open the file `%USERPROFILE%\.codex\config.toml` in Notepad (create the `.codex`
   folder and the file if they do not exist). The Codex app, the Codex CLI and the IDE
   extension all use this file.
2. Add these lines:

   ```toml
   default_permissions = "workspace-net"

   [permissions.workspace-net]
   extends = ":workspace"

   [permissions.workspace-net.network]
   enabled = true
   ```

   This keeps Codex's normal workspace limits (it can only change files in your project) and
   adds internet access for commands.
3. If the file already has `sandbox_mode` or a `[sandbox_workspace_write]` section, delete
   those lines: the old and the new setting cannot be used together.
4. Restart Codex.

Official reference: <https://learn.chatgpt.com/docs/permissions>. If commands still cannot
reach the internet, choose **Full access** under the message box only for this project and
only while needed. OpenAI warns that full access can lead to unintended changes, so switch
back to **Ask for approval** afterwards.

## 4. Install uv and the project tools

1. Install **uv** (it installs Python 3.13 for you). In PowerShell:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Then close and reopen Codex. Details: <https://docs.astral.sh/uv/getting-started/installation/>
2. Ask Codex: **"Run uv sync in this project."** This installs everything else, including
   FFmpeg for videos.

## 5. The `.env` file (settings, no keys)

1. `.env` comes with the project (git clone); it is committed and holds no keys. Without git,
   copy `.env.example` and name the copy `.env`.
2. Its settings:

   | Line | Value | Why |
   | --- | --- | --- |
   | `IMAGE_PROVIDER=` | `codex_builtin` | real non-Roman images by Codex's built-in image generation, $0 (`openrouter` to opt in to OpenRouter; `mock` for free test pictures) |
   | `OPENROUTER_API_KEY=` | stays empty in `.env`; your key from <https://openrouter.ai> (Settings → Keys; add credits first) goes into a Windows environment variable (step 3) | only with `IMAGE_PROVIDER=openrouter` |
   | `IMAGE_MODEL=` | `google/gemini-3.1-flash-image` | the image model |
   | `SCRAPER_PROVIDER=` | `free` | real news (our own free scraper) |
   | `USER_NAME=` | your name | saved in every job record |

   `VIDEO_PROVIDER=higgsfield-plugin` and `VOICE_PROVIDER=none`
   are already set (see step 8); `IMAGE_DAILY_LIMIT=30`.
3. Keys: `.env` is committed to git, so a key never goes into it. Set it as a Windows user
   environment variable instead, in PowerShell: `setx OPENROUTER_API_KEY "<key>"`, then restart
   Codex (it overrides the empty `.env` line). **Never paste a key into the Codex chat, a
   document or a screenshot.**

## 6. Add the reference photos

Put the files in these folders inside the project (create them if needed):

| Folder | What goes in it |
| --- | --- |
| `assets/reference/identity/person_01/` | 4–10 clear photos of the person (face visible, at least 512 px). Only photos of people who agreed to this use. |
| `assets/reference/brand/logo/` | the logo as a PNG with a transparent background (the app pastes it onto every design) |
| `assets/reference/creative/facebook_ads/` | a few past ads, used as style examples |
| `assets/reference/creative/facebook_ads/` | the 6 past ads (masked copies are made from them; see below) |

Then ask Codex: **"Run uv run ca refs frames, uv run ca refs scan and uv run ca refs mask."**
The photos stay out of git, but what was decided about them comes with the project: the brand
profile (`config/brand.json`) and the style tags, primary photos and logo areas to cover
(`config/references.json`) are applied by the scan, and `ca refs mask` makes the logo-free
copies of the past ads. More detail: [Module 1 guide](guides/module-1-images.md).

## 7. Check everything

Ask Codex: **"Run uv run ca doctor."** It checks the tools, your `.env` (it shows only whether
each key is set, never the key itself), the photos, `brand.json`, the company profile
(`brand/services.md`), the news sites, the providers and the output folders. Every
`[FAIL]` line comes with a **Fix:** line; do that and run it again until there are no problems.
`[WARN]` lines are fine for a start (for example an old `.env` line that `ca doctor` asks you
to change).

## 8. Plugins: Gmail and Higgsfield

Codex uses two plugins: **Gmail** (read-only, for "show content") and **Higgsfield** (Roman's
images with Soul 2.0 and his saved character, and reel clips). Install and sign in to them in
Codex; nothing goes into `.env` except the provider names above. (v6: HeyGen is no longer used.)
Optional: the **Google Drive** plugin, read-only, to look up files, links and the Content
Tracker. Uploads and tracker updates never use it; they go through `ca drive` and `ca tracking`.

## 9. Google Drive and the Content Tracker (optional)

Finished images and videos go to Google Drive (`Content Automation/LinkedIn`, `Facebook`,
`Instagram`, `Calendar`), and each finished post gets a row in the **Content Tracker** Google
Sheet, where the social media manager sets Approval status, Publishing status and Publication
date. Until this is set up, everything is saved in `outputs/drive/` instead (`STORAGE_PROVIDER=mock`).

In Google Cloud (console.cloud.google.com), signed in with the Google account that should own
the folders:

1. Create a project, e.g. "Content Automation".
2. **APIs & Services → Library**: enable the **Google Drive API** and the **Google Sheets API**.
3. **Google Auth Platform → Get started** (the OAuth consent screen): app name, support email,
   Audience **External** (or **Internal** with Google Workspace), contact email, **Create**.
4. **Data Access → Add or remove scopes**: tick `https://www.googleapis.com/auth/drive.file`
   (it covers Drive and Sheets, only for files the app made) and save.
5. **Audience**: click **Publish app** (no review is needed for this scope), or add your account
   as a **Test user**; in testing mode the sign-in expires after 7 days and step 8 must be repeated.
6. **Clients → Create client**: Application type **Desktop app**, **Create**, **Download JSON**.
7. Save the file in this project as `.secrets/google_oauth_client.json` (the folder is git-ignored;
   never paste its contents into a chat).
8. Optional: in `.env`, set `DRIVE_SHARE_WITH=` to the manager's email (comma-separated for
   several); they get editor access to the main folder, and nothing is made public. Then ask
   Codex: **"Run uv run ca drive setup."** A browser opens once for the Google sign-in; the
   folders and the Content Tracker are made.
9. In `.env`, set `STORAGE_PROVIDER=drive`, then run `uv run ca doctor` (the Drive line should say "set up").

After that, every finished package is uploaded and added to the tracker by itself. Say
**"sync drive"** to retry failed uploads, **"show tracker"** for the status counts and
**"export tracker"** for a CSV copy.

## 10. Try it: example requests

Type these into Codex (one at a time):

1. "Make an Instagram post about AI chatbots for small businesses."
2. "Make a LinkedIn post and an ad about marketing automation for SMEs."
3. "Make a reel about lead generation with AI."
4. "What are this week's biggest SEO trends? Give me 3 content ideas."
5. "Make 3 Instagram photos of me presenting our AI marketing automation service."

For 1–3, Codex creates a package folder in `outputs/content/`, writes the brief, shows you the
cost and waits for your OK before making anything. When it is done, it replies with the folder
and the list of files (images, video, `post.md` with the caption, hashtags and sources).
