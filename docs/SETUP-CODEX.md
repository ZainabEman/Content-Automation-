# Set up Codex Desktop for Content Automation

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
and making images with OpenRouter. By default Codex runs commands without internet. To allow
it, edit Codex's settings file:

1. Open the file `C:\Users\<your name>\.codex\config.toml` in Notepad (create the `.codex`
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

## 5. Create your `.env` file (your private settings)

1. In the project folder, copy `.env.example` and name the copy `.env`.
2. Open `.env` in Notepad and set:

   | Line | Value | Why |
   | --- | --- | --- |
   | `OPENROUTER_API_KEY=` | your key from <https://openrouter.ai> (Settings → Keys; add credits first) | real images |
   | `IMAGE_PROVIDER=` | `openrouter` | real images (use `mock` for free test pictures) |
   | `IMAGE_MODEL=` | `google/gemini-3.1-flash-image` | the image model |
   | `SCRAPER_PROVIDER=` | `free` | real news (our own free scraper) |
   | `USER_NAME=` | your name | saved in every job record |

   Leave `VIDEO_PROVIDER=mock`, `AVATAR_PROVIDER=mock` and `VOICE_PROVIDER=none` for now (see
   step 8).
3. Save the file. **Never paste a key into the Codex chat, a document or a screenshot**:
   it belongs only in `.env`, which is never shared or uploaded.

## 6. Add the reference photos

Put the files in these folders inside the project (create them if needed):

| Folder | What goes in it |
| --- | --- |
| `assets/reference/identity/person_01/` | 4–10 clear photos of the person (face visible, at least 512 px). Only photos of people who agreed to this use. |
| `assets/reference/brand/logo/` | the logo as PNG or JPG |
| `assets/reference/creative/facebook_ads/` | a few past ads, used as style examples |
| `assets/reference/brand/brand.json` | colours, fonts, tone and rules (already there for Branded Genius) |

Then ask Codex: **"Run uv run ca refs scan."** More detail: [Module 1 guide](guides/module-1-images.md).

## 7. Check everything

Ask Codex: **"Run uv run ca doctor."** It checks the tools, your `.env` (it shows only whether
each key is set, never the key itself), the photos, `brand.json`, the company profile
(`docs/company/services.md`), the news sites, the providers and the output folders. Every
`[FAIL]` line comes with a **Fix:** line; do that and run it again until there are no problems.
`[WARN]` lines are fine for a start (for example "mock" video while Higgsfield is not connected).

## 8. Later: connect Higgsfield and HeyGen (videos)

Reels use placeholder clips until the video services are connected. When you are ready,
follow [Connect Higgsfield and HeyGen in Codex](guides/module-2-video.md#connect-higgsfield-and-heygen-in-codex).

## 9. Try it: example requests

Type these into Codex (one at a time):

1. "Make an Instagram post about AI chatbots for small businesses."
2. "Make a LinkedIn post and an ad about marketing automation for SMEs."
3. "Make a reel about lead generation with AI."
4. "What are this week's biggest SEO trends? Give me 3 content ideas."
5. "Make 3 Instagram photos of me presenting our AI marketing automation service."

For 1–3, Codex creates a package folder in `outputs/content/`, writes the brief, shows you the
cost and waits for your OK before making anything. When it is done, it replies with the folder
and the list of files (images, video, `post.md` with the caption, hashtags and sources).
