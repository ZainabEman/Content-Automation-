# Manual: making social media graphics with Codex

This manual is for the social media designer. You never need to write code. You type a short sentence (a "phrase") in Codex Desktop, and Codex does the work for you.

## Four things to know first

1. **Every post has an ID** such as `BG-125`. Use it whenever you talk about a post ("status BG-125").
2. **Nothing is made until you say "ok".** Before any images are created, Codex shows a plan: what it will make and how many images. Read it, then type **ok**. Without your "ok", nothing happens.
3. **Nothing is posted automatically.** You decide what goes online and when.
4. **All text the audience sees is German.**

## Your weekly routine

Every week has the same set:

- **14 image posts**: 2 posts with Roman (one LinkedIn post, one Facebook post), 2 Instagram carousels and 10 more posts shared fairly between LinkedIn posts, Facebook posts and Facebook ads (4, 3 and 3; which one gets 4 changes every week).
- Two posts a day. The same kind of post never appears on 3 days in a row.
- **2 long YouTube scripts** and **4 short YouTube scripts** (see "YouTube scripts" below).

A month is four weeks: 56 image posts (8 with Roman, 8 carousels, and 40 shared 14, 13 and 13 between LinkedIn posts, Facebook posts and Facebook ads), 8 long and 16 short scripts. Type `make weekly calendar` for one week or `make monthly calendar` for a whole month.

| Step | Type this in Codex | What happens |
| --- | --- | --- |
| 1 | `make weekly calendar` (or `make calendar next week`) | Codex suggests next week's 14 posts (date, topic, platform) and plans the week's 6 YouTube scripts. |
| 2 | `approve all` or `approve 1 3 5` | You accept all rows or only the rows you name. |
|   | `reject 2` | You turn a row down. Codex asks you why. |
| 3 | `review copy for next week` | You read the headline, text and button of every graphic. |
|   | `rewrite copy for next week` | Codex writes the text again if you don't like it. |
| 4 | `generate approved` | Codex shows the plan: the posts, the layouts and the number of images. |
| 5 | `ok` | Codex prepares the images. |
| 6 | `generate images` | Codex creates the pictures (one per image, only once). |
| 7 | `import images` | The pictures go into your designs: text, logo and button are added and checked. |
| 8 | `sync drive` | The finished files go to Google Drive. Every successful upload also updates the post's row in the Content Tracker (with the Drive folder link). If the tracker could not be updated, Codex tells you. |

Codex often runs steps 6 and 7 by itself. If it stops and says **"CODEX IMAGES … wait for Codex"**, just type `generate images`.

## Making a single post

- `make a post about <topic>`: a post about your topic.
- `make an insta carousel about <topic>`: an Instagram carousel (5–6 square slides).
- `make a facebook ad about <topic>`: one ad image plus the ad texts.
- `make a post about <topic> as FB-2`: the same, in a layout you choose (see the list below).

After each one, Codex shows the plan. Type `ok` to make it.

### The layouts you can choose

| Platform | Layouts |
| --- | --- |
| Facebook post | FB-1 Panel + Visual, FB-2 Before / After, FB-3 Icon Row, FB-4 Light Sweep |
| Facebook ad | FA-1 Offer Panel, FA-2 Before / After Ad, FA-3 Feature Ad |
| LinkedIn | LI-1 Headline + Visual, LI-2 Panel + Visual, LI-3 Icon Row, LI-4 Light Sweep |
| Instagram carousel | CS-1 Neon Statement, CS-2 Numbered Points, CS-3 Centred Cover, CS-4 Condensed Blocks |
| With Roman | FB-R1, FA-R1, LI-R1 (Founder) |

If you don't choose one, Codex picks a layout so that posts don't repeat.

## YouTube scripts

There are two kinds of script. Codex only writes scripts; no video or voice is made.

| Type this in Codex | What you get |
| --- | --- |
| `make short video script` | About 1 minute: a conversation between the AI host (`HOST:`) and Roman (`ROMAN:`) about one problem in Germany: bad news in tech, AI risks, harm to people and jobs, or AI limits. It starts with a negative hook, then one number, 2–3 points and a solution. |
| `make long video script` | About 12 minutes: Roman alone, 5–10 news topics, in three styles (Style A, B and C). |

Each script folder holds three files:

- `script-en-de.md`: the script in English and German, paragraph by paragraph.
- `teleprompter-de.txt`: the German text Roman reads (in short scripts, Roman's lines start with `ROMAN:`).
- `storyboard.md`: the plan for the video editor. The source of each fact (article title, outlet, date and link) sits right under the scene it belongs to. There is no separate sources file.

A short script has the three files directly in its folder. A long script has one folder per style (`Style A`, `Style B`, `Style C`), each with the same three files and its own storyboard.

Then: `research BG-x`, `check sources BG-x`, `write scripts BG-x`, `generate storyboards BG-x` and `upload youtube BG-x`. The upload also updates the Content Tracker.

## When Codex stops and asks you to look

Sometimes Codex stops and shows you an image. Look at it carefully and answer:

- **Person check** (images with Roman): does he look like Roman? Answer pass or fail and say what you see.
- **Set check** (carousels): do all slides look like one set (same fonts, colours, style)?
- **Visual review**: is the text readable, is nothing on top of anything else, is the logo right, is the German correct? Answer yes or no for each one.

If something is wrong, say what is wrong. Nothing is made again until you agree.

## Looking at designs (free)

- `preview designs`: every layout drawn with sample text.
- `compare designs`: our layouts next to the company's own graphics.
- `check designs`: checks brand colours, logo, text size and contrast.
- `preview overlay BG-x`: Roman's post with its text, before anything is made.

## Changing or fixing a post

- `revise BG-x <your feedback>`: a new version with your changes (needs your approval again).
- `regenerate BG-x`: makes the images again (Codex shows the plan first, then you type `ok`).
- `redo slide 3 of BG-x`: makes only that slide again; the other slides stay.
- `reject BG-x <reason>`: turns a post down.

## Checking where things are

- `what's pending`: what is waiting for you.
- `what needs review`: finished posts you have not looked at yet.
- `status BG-x`: everything about one post.
- `show calendar`: next week's calendar.
- `show tracker`: the Content Tracker rows.
- `what can I say`: every phrase Codex understands.

## Where the finished files are

On Google Drive (in `Content Automation`) and on this computer, in the `outputs` folder:

- `Instagram/Carousels/…`, `Facebook/Posts/…`, `Facebook/Ads/…`, `LinkedIn/Posts/…`
- YouTube scripts: `YouTube Short-form` and `YouTube Long-form` on Drive (`YouTube Short-Form` and `YouTube Long-Form` on this computer).
- One folder per post or script, named with its English topic and its date, for example `AI in Sales 2026-11-03`. If two have the same name, the second gets ` (2)`.
- File names are English; the text inside stays German.
- The ID (for example `BG-125`) is not in the folder name. You find it in the Content Tracker and in the file `item.json` inside the folder.
- In a post folder: `final/` (the images ready to post) and `caption_de.txt` (the German caption).

### Renaming older folders

Folders made before this change have the old names (for example `2026-11-03_BG-125_ki-im-vertrieb`). To give them the new names:

1. Type `rename folders`. Codex only shows a list: each old name and its new name. Nothing changes yet. If a folder has no English title yet, Codex writes one first.
2. Check the list. If it looks right, type `ok`.
3. Codex renames the folders on this computer and on Google Drive (same folders, same files, only the name changes) and updates the Content Tracker.

## Brand rules the app follows for you

- **Logo**: the "bg" favicon, always in its own colours (blue "b" and "G", silver disc), small, in the top corner. It is never recoloured, stretched or turned white.
- **Carousels**: logo and website only on the last slide, no slide numbers.
- **Roman's images**: no logo and no website.
- **Pictures**: the image generator never writes text or logos. The app adds all text, the logo and the button, so the spelling is always exactly what you approved.
- **Colours**: the brand colours on a dark navy background.

## Please don't

- Don't paste passwords or keys into the Codex chat.
- Don't edit the calendar files by hand. Use `approve`, `reject` and `revise` instead.
- Don't rename or move files inside the `outputs` folder yourself. Use `rename folders` instead.

If something fails or looks strange, copy Codex's message and send it to the person who set up the system.
