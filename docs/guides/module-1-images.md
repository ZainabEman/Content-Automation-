# Module guide: Images

> Status: Module 1 is built and tested offline (job records, reference library, brand profile,
> the three workflows, the Codex playbook, and the OpenRouter provider).
> Real images are made through **OpenRouter** (the Gemini image model, paid per image).

## What it does

It makes images from a text description and saves each request in its own dated folder,
with a `details.json` file that records exactly what was asked, what was sent, and what came back.

With the free **mock** provider it makes placeholder images (your prompt as text on a coloured
card at the right shape), so you can try the whole flow without spending money. With
`IMAGE_PROVIDER=openrouter` it makes real images with Google's Gemini image model through
OpenRouter (paid, see "Costs and limits").

**Consent:** the company lead provided his own photos for his company's marketing. Only use
photos of people who have agreed to this use.

## What was built

- **Job records**: every request gets a folder and a `details.json` with its status
  (`queued`, `processing`, `completed`, `failed`, or `cancelled`).
  A job is only marked `completed` when all its image files really exist.
- **Daily limit**: the tool counts today's finished real (non-mock) images and refuses new
  requests once `IMAGE_DAILY_LIMIT` is reached, before contacting any provider.
- **Dry run** (`--dry-run`): shows the final prompt, which reference photos would be sent,
  how many provider calls it takes and the estimated cost, without making anything.
- **OpenRouter provider** (the one used for real images): the Gemini image model
  `google/gemini-3.1-flash-image` through OpenRouter. The real price of each request is saved
  as `actualCostUsd` next to the estimate.
- **Time limit and retries**: a request that takes too long is stopped and marked failed.
  Temporary provider errors (such as "busy") are retried; timeouts are not retried, so you
  are never charged twice for one request.
- **Safe logs**: secret keys are hidden (`***`) in anything the tool prints or saves.
- **One image interface** with a mock provider, so real providers can be added later
  without changing how you use it.
- **Reference library**: the tool reads your photo folders where they are (nothing is moved
  or deleted), checks each photo, gives it a permanent ID, and makes a smaller copy for sending.
  Four kinds are kept separate: `identity` (the person), `product`, `brand` (logos), and
  `creative` (past ads and carousels, used only as **style** examples, never as the person's face).
- **Style tags**: every style example is tagged once, by looking at it: does it show people
  (a person, face, hand or human figure) and does it show a logo? The tags are saved in each
  set's `set.json` (`"people"`, `"logo"`) and survive a rescan. On 2026-10-04 all 318 were
  tagged: 197 show neither, 51 show people, 62 show a logo. For a new style image: look at it,
  then `uv run ca refs tag --asset <id> --people yes|no --logo yes|no` (`uv run ca refs list`
  shows how many are still untagged).
- **Primary photos**: for each person, the 4 best photos are marked "primary". These are
  the ones sent to the image model.
- **Brand profile** (`brand.json`): colours, fonts, tone and do/don't rules, drafted from the
  brand style guide PDF for you to check.
- **Video frames**: carousel videos are turned into still frames (3 per video) so they can be
  used as style examples.
- **Three workflows** that turn a short scene description into a full prompt: they add the
  right reference photos, say what each photo is for (the person, a product, or style only),
  and add the brand rules from `brand.json` automatically. Any text in an image is in English.
- **Design system** (`config/design_system.json`), in three parts:
  - a fixed **core** that is always on: the brand colours (named by role: background,
    accent/glow, highlight, text; the actual colours come from `brand.json`), the fonts, the
    empty logo corner, the identity rules, "no readable text on screens or signs" and the
    text-accuracy rules;
  - **pools** of things that vary: 16 scenes (office by day or night, studio, cafe, city street,
    home desk, conference stage, co-working space, reception desk, clinic, shop, a real estate
    office, a staged home interior, a house front, two abstract backgrounds), 6 wardrobes
    (smart-casual to suit), props, decor, hologram styles and poses. Scenes made for one trade
    (reception desk, clinic, shop, the three real estate scenes) are used only when the topic
    names that trade, so a real estate post never gets a clinic-style reception;
  - seven post **formats** (see "Designed graphics"). The glass text panel, holograms, decor and
    props are optional parts: each format shows only the ones it lists.
- **Variety**: what you do not set (scene, wardrobe, props, decor, pose) is picked from the pools
  and avoids what the last 5 content packages used. The same request always gets the same picks,
  so a dry run shows what the real run will use. The picks are saved in `details.json`
  (`inputs`) and, for packages, in `package.json` (`picks`). The style examples rotate too: ads
  use up to 3 past ads (`creative/facebook_ads`); carousels use the 13 demo carousels in
  `creative/carousels`, picked by slide role (slide 1 of a demo for the hook, its last slide for
  the call to action, the slides between for tips); other formats use none. Within one carousel
  all slides share one scene, decor and palette, and slides 2+ also attach slide 1's image
  (the version without the logo). Style examples with a logo are never sent, and images that
  show the man get only examples with no people and no logo (or none: today no past ad
  qualifies, since all 6 show the logo and 4 show people).
- **Consistent person (compulsory)**: any human in any image, slide or video is the person from
  `DEFAULT_IDENTITY_SET`. Every design that shows him (format ad with layout B, C or D, news with
  a person, person photo, carousel hook slide) and every video gets all his reference photos; a
  clear error stops it if they are missing. The prompt tells the model to keep exactly that face,
  hair, skin tone and age, that he is the only person, and not to beautify him or add glasses, a
  beard or accessories. Designs without him say: no people, faces or human figures. His photos
  are attached first (primary photos first) and the prompt says he is the only person allowed:
  any person, face or logo in another reference image is ignored. His face is never described
  in words and never taken from style examples or slide 1; the 14-image limit never drops his
  photos. `details.json` records `personShown`, `identityRefs` and `references` (every image
  sent, in order, with its tags).
- **Person check** (content packages): each image with the man is made on its own and the build
  stops after it. Codex looks at it beside two of his primary photos. If he clearly differs
  (hair, build, facial hair, age) it records `uv run ca job review <job folder> --fail "..."`,
  shows you the image and asks before making it again (with the cost); otherwise `--pass` and
  the build goes on. The result is saved in `details.json` (`reviews`). A slide 1 that failed is
  never used for the later slides.
- **Logo, pasted by the app**: the image model is never asked to draw the logo (it used to invent
  one). The prompt keeps the top-right corner empty, and the app pastes the real logo file there
  at one fixed size and place on every image: 20% of the width, a small margin from the top and
  right edge (on 9:16 just below the top safe zone). The file is `logoFile` in `brand.json` and
  must have a transparent background (now `logo (1).png`; `cFkuqb.jpg` has a white background).
  The model's own image is kept in the job's `raw/` folder.
- **Exact text only**: the image shows only the texts you give (headline, subheadline, CTA label,
  big number, steps, icon labels, slide number), exactly as written and in the language of
  `brand.json`.
- **Readable, on-brand, for someone**: every design fills the canvas with text sized for a phone, sets headlines in the brand heading font from `brand.json` (never condensed), and shows the website from `services.md` as a small footer. Statement, stat and checklist posts and the carousel hook carry a small audience line (`--audience-line "For dental practices"`). Carousel tip slides can show the automation: `--chat "Customer: ...|Bot: ..."` (2-3 bubbles) or `--diagram "Visitor asks|Chatbot answers|Lead in CRM"`. The scene is picked by relevance to the topic first (reception desk, clinic, shop, office, ...), then rotated.
- **Real numbers only**: a `stat` post is refused unless its number is written in the saved
  research article you name as its source.
- **Services, not products**: `person_service` shows the person delivering one of the
  company's services, described in words (no product photos needed).
- **Company profile** (`docs/company/services.md`): who Branded Genius is, its 7 services, core
  message and content rules. Codex reads it for scenes, headlines and captions, and the tool
  adds the company line and the content rules ("never invent results, statistics, prices or
  client names") to every prompt that needs them.

## One-time setup

1. Install uv using the [official installer](https://docs.astral.sh/uv/getting-started/installation/).
2. In the project folder, run `uv sync`.
3. Make sure `.env` exists (copy `.env.example` if not). Use `IMAGE_PROVIDER=mock` to try
   things for free.
4. Check it works: `uv run ca hello`.

### Set up OpenRouter (real images)

1. Create an account at [openrouter.ai](https://openrouter.ai), add some credits
   (Settings → Credits), and create an API key (Settings → Keys).
2. Open `.env` in a text editor and set:
   ```
   IMAGE_PROVIDER=openrouter
   IMAGE_MODEL=google/gemini-3.1-flash-image
   OPENROUTER_API_KEY=<paste your key here>
   ```
   Keep the key only in `.env`: never paste it into Codex, chat, documents or screenshots.
3. Test without spending anything: add `--dry-run` to any image command. It shows the photos
   that would be sent and the estimated cost.

### Add your photos

Put photos in `assets/reference/`. The **first folder** is the kind, the **folder inside it** is a set:

```
assets/reference/
  identity/person_01/        photos of one person (clear face, different angles)
  product/<product-name>/    product photos (optional; only social_creative uses them)
  brand/logo/                logos
  brand/guidelines/          brand style guide PDF (read for brand.json, not sent)
  creative/facebook_ads/     past ads (style examples)
  creative/carousels/<name>/ carousel slides (style examples)
```

- Use **JPG, PNG or WebP**. SVG and PDF files are listed as "rejected". To use a PDF
  carousel, export its pages as PNG/JPG images.
- **Videos** (MP4): run `uv run ca refs frames` once. It saves 3 still frames of each video
  (at 10%, 50% and 90%) in a `_frames/` folder next to it; the scan then uses those frames.
- Photos must be at least **512 px** on the short side (logos: **256 px**).

### Scan the folders

```
uv run ca refs frames   (only if you added videos)
uv run ca refs scan
```

This lists each set with how many photos were accepted, rejected (with the reason) and marked
primary. Run it again any time you add, change or remove photos. IDs and your primary choices are kept.

### Choose the 4 primary photos

The first scan marks the first 4 photos (by file name) of each person as primary. To choose
others, see the file names in the set folder and run:

```
uv run ca refs primary --set identity/person_01 --files 2.jpg,5.jpg,7.jpg,9.jpg
```

Pick sharp, well-lit photos where the face is clearly visible, ideally from different angles.

### Check brand.json

Open `assets/reference/brand/brand.json` in any text editor, or run `uv run ca brand show`.
Fix anything wrong, remove each item from `needsReview` once you have checked it, and change
`"status": "draft"` to `"status": "approved"` when you are happy. `logoFile` is the file in
`brand/logo/` that the app pastes onto every design; it must be a PNG with a transparent
background. `language` is `"en"`, so any text in an
image is written in English. `services` lists the company's 7 services (from
`docs/company/services.md`); pick one for `person_service`. To change what the company offers,
edit `docs/company/services.md` and `services` in `brand.json` together.

## How to use

For a complete post, ad and reel about a topic, use the content flow in the [Module 3 guide](module-3-research.md#make-a-content-package); it uses these image workflows for you. This section is about single image requests.

The easiest way: **ask Codex in plain English**. Codex follows the "Make images" playbook in
`AGENTS.md`. It picks the workflow, the photos and the shape, writes a detailed scene
description, runs the command, and replies with the folder and one line per image.

The three workflows:

| Workflow | Use it for | Needs |
|---|---|---|
| `person_lifestyle` | The person in a real-life scene | `--set` (the person); style set optional |
| `person_service` | The person delivering or presenting one of the company's services | `--set` and `--service "…"` (the service in words) |
| `social_creative` | A designed post in one of seven formats | `--format` and its texts (see "Designed graphics" below); the logo and, where the man is shown, his photos are added automatically |

If Codex doesn't specify them, the shape is 4:5 (Instagram feed) and it makes 3 versions. Brand colours,
tone and "don't" rules are added automatically, so you don't need to repeat them.

### Designed graphics (how Codex chooses)

First the **format** (`--format`, default `ad`). Each format takes only its own texts; anything
else is refused with a message that names what to change.

| Format | What it shows | Texts | Person | CTA button |
|---|---|---|---|---|
| `ad` | Headline, subheadline and button in the glass panel, with holograms | `--headline` (max 6 words), `--subheadline`, `--cta`; optional `--icons`, `--visual` | With layout B, C or D | Yes |
| `statement` | One bold sentence, large, on the background | `--headline` (the sentence, max 12 words) | No | No |
| `stat` | One big number and one context line | `--stat "58%"`, `--subheadline` (context), `--source <articleId>` | No | No |
| `news` | The news in one line, then "What it means" | `--headline` (max 14 words), `--subheadline`; optional `--source` | Only with `--layout B` or `C` | No |
| `carousel` | One slide: hook (slide 1), tips, call to action (last slide) | `--slide N/TOTAL`, `--headline`; optional `--subheadline`, `--visual` (tip icon); `--cta` on the last slide only | Slide 1 only | Last slide only |
| `person_photo` | The man in a scene, no panel, logo only | Optional `--headline` of 0–3 words | Yes | No |
| `checklist` | A title and 3–5 numbered steps with icons | `--headline` (title), `--steps "One\|Two\|Three"` | No | No |

A `stat` number must be written in the research article given as `--source` (the IDs are in a
package's `research.md` or in `uv run ca research digest`); otherwise the request is refused.

Then the details:

| Choice | Options | How to pick |
|---|---|---|
| `--kind` | `organic` (default), `ad`, `story` | **Organic** = educational; a soft CTA where the format has one ("Learn more", "Read now"). **Ad** (only with format `ad`) = one message, one offer, one CTA; offer words (free, analysis, demo, in 15 minutes); at most one proof number and only if it is real (from `docs/company/services.md`); short text; 3 variants. **Story** = 9:16 with the top and bottom 13% kept free of text and logo. |
| `--layout` (format `ad`) | `A`, `B`, `C`, `D` | **A** text left + system visual right, no person (product or feature). **B** text left + person right, **C** person left + text right (trust and authority; alternate B and C between posts). **D** before/after split: the same person stressed on the left, relaxed on the right (pain vs gain). |
| `--headline` + `--highlight` | 1–2 highlight words from the headline | Format `ad`: use one formula: contrast, pair, principle, question, idiom twist or promise (examples in `config/design_system.json`). Shown in capitals (not in `news`). |
| `--subheadline` + `--sub-highlight` | one short sentence; one highlight word | Format `ad`: always fill it. |
| `--cta` + `--cta-icon` | button label; `arrow`, `calendar`, `play` | The icon follows the action: arrow (learn/try/analyze), calendar (book), play (demo); it is chosen from the label unless you set it. |
| `--icons` (format `ad`) | 3–4 labels of 1–2 words | Optional icon row, e.g. `"Chatbots,CRM,Email"`. |
| `--visual` | free text | Layout A: what the system visual shows. Carousel tip slide: what the icon shows. |
| `--scene`, `--wardrobe`, `--props`, `--pose` | an ID from the pools in `config/design_system.json`, or your own words | Usually leave them out: they are picked for variety. Set one only when you want something specific. |

Shapes: organic 4:5 (or 1:1), ads 1:1 or 4:5, stories 9:16. Designed graphics are made at 2K.
The app pastes the logo at the top right (the model leaves that corner empty). Never describe
the man's face. A stat post also shows a small "Source: ..." line: `--source-name` (brief:
`sourceName`) is the article's publisher in short, e.g. "Zillow"; left out, the article's source
is used, and a name that is not the article's publisher is refused.

### Example Codex requests

1. "3 Instagram options of me working at a café"
   ```
   uv run ca image --workflow person_lifestyle --set identity/person_01 --aspect 4:5 --count 3 --prompt "Working on a laptop at a bright modern café, relaxed smile, morning window light, 35mm, shallow depth of field" --request "3 Instagram options of me working at a café"
   ```
2. "A story of me speaking on stage at a marketing conference"
   ```
   uv run ca image --workflow person_lifestyle --set identity/person_01 --aspect 9:16 --count 3 --prompt "Speaking on a conference stage with a microphone, audience in soft focus, blue stage lights, low angle, 24mm" --request "A story of me speaking on stage at a marketing conference"
   ```
3. "2 LinkedIn photos of me running a strategy workshop"
   ```
   uv run ca image --workflow person_service --set identity/person_01 --service "Business strategy workshop for small companies" --aspect 1:1 --count 2 --prompt "Leading a whiteboard session with three attentive clients in a bright modern meeting room, mid-gesture, natural window light, 35mm" --request "2 LinkedIn photos of me running a strategy workshop"
   ```
4. "A Facebook ad saying 'Grow faster with AI', with me in it" (3 variants by default)
   ```
   uv run ca image --workflow social_creative --format ad --kind ad --layout B --headline "Grow Faster With AI" --highlight "AI" --subheadline "One AI marketing system for content, leads and follow-ups." --sub-highlight "system" --cta "Book a demo" --aspect 4:5 --request "A Facebook ad saying 'Grow faster with AI', with me in it"
   ```
5. "A bold statement post: AI does not replace your team, it frees it"
   ```
   uv run ca image --workflow social_creative --format statement --headline "AI does not replace your team. It frees it." --highlight "frees" --count 3 --request "A bold statement post: AI does not replace your team, it frees it"
   ```
6. "A stat post with the 58% from the AEO article"
   ```
   uv run ca image --workflow social_creative --format stat --stat "58%" --source <articleId> --subheadline "<what the article says the 58% measures>" --count 3 --request "A stat post with the 58% from the AEO article"
   ```
7. "A checklist post: how to set up lead follow-up"
   ```
   uv run ca image --workflow social_creative --format checklist --headline "Set Up Lead Follow-Up" --steps "Capture every inquiry in one place|Answer the first question with a chatbot|Send a follow-up within one day" --count 3 --request "A checklist post: how to set up lead follow-up"
   ```
8. "A photo of me in a cafe for Instagram, no text"
   ```
   uv run ca image --workflow social_creative --format person_photo --scene cafe --count 3 --request "A photo of me in a cafe for Instagram, no text"
   ```
9. "The first slide of a 5-slide carousel: '3 AI tools every marketer needs'" (run it again with
   `--slide 2/5` … `5/5` and `--first-slide <jobId>/image-1.png` so the later slides match slide 1;
   all slides of one carousel get the same scene and decor)
   ```
   uv run ca image --workflow social_creative --format carousel --slide 1/5 --headline "3 AI Tools Every Marketer Needs" --highlight "AI Tools" --subheadline "Swipe to see where to start." --request "The first slide of a 5-slide carousel: '3 AI tools every marketer needs'"
   ```

### Running a command yourself

- `--workflow`: one of the three workflows above. Leave it out for "raw" mode: the prompt is
  sent exactly as written, with no photos or brand rules.
- `--prompt`: what the picture should show (required for photos and raw mode; not needed for
  `social_creative`, where it is taken as the scene if you give one).
- `--set`, `--style`: which reference sets to use (see `uv run ca refs list`).
- `--service`: for `person_service`, the service shown, in words.
- `--product`: for `social_creative` only, a product photo set (if you ever add one).
- `--format`, `--kind`, `--layout`, `--pose`, `--scene`, `--wardrobe`, `--props`, `--headline`,
  `--highlight`, `--subheadline`, `--sub-highlight`, `--cta`, `--cta-icon`, `--icons`,
  `--visual`, `--stat`, `--source`, `--steps`, `--slide`, `--slide-role`: for `social_creative`
  only (see "Designed graphics" above). `--variant` is the old name of `--kind` (`post` =
  `organic`); `--logo` is no longer needed there.
- `--set` with `social_creative`: only to show a different person than `DEFAULT_IDENTITY_SET`.
  Designs without a person take no `--set`.
- `--style` with `social_creative`: only to force one style set; normally the style examples
  are chosen per format and rotate.
- `--aspect`: `1:1` square, `4:5` Instagram portrait, `9:16` story/reel, `16:9` wide (photos
  only). Designs allow: organic and carousel 4:5 or 1:1, ads 1:1 or 4:5, stories 9:16.
- `--count`: how many versions, 1 to 4. Default 1, ads 3 (Codex uses 3).
- `--request`: your original words, saved in `details.json`.
- `--style-count`: how many style images to send (default 3). They are taken from different
  videos/files, spread across the set.
- `--dry-run`: show the prompt, reference photos, number of calls and estimated cost. Nothing
  is created, nothing is sent, and it does not count toward the daily limit. No API key needed.

If something required is missing, the tool stops with a clear message **before** creating a
job or contacting any provider.

## Commands

| Command | What it does |
|---|---|
| `uv run ca hello` | Shows your settings (keys are hidden). |
| `uv run ca image --workflow <id> --set … --prompt "…" [--service "…"] [--style …] [--aspect 4:5] [--count N] [--request "…"]` | Makes photos with a workflow and prints the output folder. |
| `uv run ca image --workflow social_creative --format … [--kind …] [--layout …] [--headline "…"] [--highlight "…"] [--subheadline "…"] [--sub-highlight "…"] [--cta "…"] [--icons "…"] [--visual "…"] [--stat "…" --source <id>] [--steps "…\|…\|…"] [--slide N/TOTAL] [--scene …] [--wardrobe …] [--props …] [--pose …]` | Makes a designed graphic in one of the seven formats. |
| `uv run ca image --prompt "…" [--aspect 4:5] [--count N]` | Raw mode: sends the prompt as written. |
| `uv run ca image … --dry-run` | Shows prompt, references, calls and estimated cost; makes nothing. |
| `uv run ca refs frames` | Saves 3 still frames of each reference video into `_frames/`. |
| `uv run ca refs scan` | Checks the reference folders and updates each set's `set.json`. |
| `uv run ca refs list [--type identity]` | Shows every set with accepted, rejected and primary counts. |
| `uv run ca refs primary --set <set> --files a.jpg,b.jpg` | Chooses up to 4 primary photos of a person. |
| `uv run ca brand show` | Shows a short summary of `brand.json` and what still needs review. |

## Outputs

Each request creates: `outputs/jobs/YYYY-MM-DD/HHmm_<short-name>/`

- `image-1.png`, `image-2.png`, …: the images.
- `details.json`: the record. Key fields: `status`, `workflowId` and `workflowVersion`,
  `request` (your words), `prompt` (the full text sent), `inputs` (sets, service, and for
  designs: format, kind, layout, the texts, the stat source, and the picks: scene, wardrobe,
  props, decor, holograms, pose),
  `identityAssetIds` / `productAssetIds` / `brandAssetIds` / `styleAssetIds` (exactly which
  reference photos were sent), `provider`, `model`, `params` (shape, size, count), `outputs`
  (file names), `error` (why it failed, if it did), `estCostUsd` (estimate), `actualCostUsd`
  (what OpenRouter actually charged), `createdAt`.

If a folder name is already taken, `-2`, `-3`, … is added. A failed job keeps its folder and
`details.json` (with the error) but has no images.

The reference scan writes, inside each set folder:

- `set.json`: the list of photos with their ID, size, `primary` flag, and `status`
  (`ok` or `rejected` with a `reason`).
- `_resized/`: smaller, upright copies (at most 1536 px) that are sent to the image model.
  Don't edit this folder; it is rebuilt by `ca refs scan`.
- `_frames/` (video folders only): still frames made by `ca refs frames`.

## Settings

Set these in `.env`:

| Setting | Meaning | Default |
|---|---|---|
| `IMAGE_PROVIDER` | Which service makes images: `mock` (free test images) or `openrouter` (real, paid). | `mock` |
| `IMAGE_MODEL` | Model name. OpenRouter: `google/gemini-3.1-flash-image`. For the mock, `mock-fail` and `mock-timeout` simulate problems; anything else works. | `google/gemini-3.1-flash-image` |
| `OPENROUTER_API_KEY` | Your OpenRouter key. Only needed when `IMAGE_PROVIDER=openrouter` (not for `--dry-run`). Keep it only in `.env`; never share it. | empty |
| `IMAGE_IDENTITY_REFS_MAX` | How many photos of the person are sent (1 to 14; the 4 primary photos first, then the others). More photos can help the likeness. | `4` |
| `IMAGE_DESIGN_SIZE` | Size of designed graphics (`social_creative`): `1K`, `2K` or `4K`. Photos stay 1K. | `2K` |
| `DEFAULT_IDENTITY_SET` | The person shown in designs with a person (layouts B, C, D, carousel hook) when no `--set` is given. | `identity/person_01` |
| `DESIGN_SYSTEM_FILE` | The design system file (look, layouts, poses, text rules). | `config/design_system.json` |
| `IMAGE_DAILY_LIMIT` | Maximum real images per day (mock images don't count). | `10` |
| `IMAGE_TIMEOUT_MS` | How long to wait for each image, in milliseconds. | `120000` (2 min) |
| `IMAGE_MAX_RETRIES` | Extra tries after a temporary error such as "busy" or "rate limit" (0 = none). | `1` |
| `OUTPUT_DIR` | Where job folders are created. | `outputs/jobs` |
| `REFERENCES_DIR` | Where reference photo folders live. | `assets/reference` |
| `USER_NAME` | Your name, saved as `requestedBy`. | `User` |

## Costs and limits

- **Mock** images are free (`estCostUsd` is 0) and don't count toward the daily limit.
- **OpenRouter** (Google's Gemini image model), estimated per image: **1K $0.067**, 2K $0.101,
  4K $0.151. Photos use 1K; designed graphics use 2K (`IMAGE_DESIGN_SIZE`). Each image is a
  separate call, so 3 photos at 1K ≈ $0.20 and 3 ad variants at 2K ≈ $0.30. The
  estimate is saved as `estCostUsd`; the real charge is saved as
  `actualCostUsd` (it can be slightly higher, because the reference photos also count).
  Always check `--dry-run` first.
- If OpenRouter's model fails (error 502) you are **not** charged, and the tool retries.
- **Live test (2026-10-01)**: one 1K 4:5 portrait cost **$0.0696** with 4 photos of the person
  and **$0.0724** with 9 photos; each took about a minute. One call with 9 photos once took over
  2 minutes and was stopped by the time limit (it was not charged). If that happens often, set
  `IMAGE_TIMEOUT_MS=300000` (5 minutes).
- Up to 4 images per request; shapes 1:1, 4:5, 9:16, 16:9.
- Reference photos per request: **14 in total at most** (the model's limit); photos of the
  person up to `IMAGE_IDENTITY_REFS_MAX` (default 4). If it would be more than 14, style
  examples are left out first; the person's photos are never dropped. The logo is not one of
  them: the app pastes it afterwards.
- The daily limit (`IMAGE_DAILY_LIMIT`) counts real images that were actually made today; when
  it is reached, requests are refused before any provider call.
- Temporary errors (rate limit, server busy) are retried per image; images already made are
  never requested twice. Timeouts are not retried.

## Troubleshooting

| Message | What to do |
|---|---|
| `Missing or invalid environment variables: X` | Fix setting X in `.env`. |
| `Daily image limit reached` | Wait until tomorrow or raise `IMAGE_DAILY_LIMIT`. |
| `OPENROUTER_API_KEY missing` | Add the key to `.env`, or use `IMAGE_PROVIDER=mock`. `--dry-run` works without a key. |
| `OpenRouter needs more credits (HTTP 402)` | Add credits at openrouter.ai → Settings → Credits, then try again. |
| `OpenRouter rejected the API key (HTTP 401)` | Check `OPENROUTER_API_KEY` in `.env` (no spaces or quotes). |
| `OpenRouter rejected the request (HTTP 400)` | Something in the request is not accepted; the details say what. |
| `OpenRouter rate limit reached (HTTP 429)` | Wait a minute and try again (it is already retried once). |
| `The image model failed (HTTP 502, not billed)` | A temporary failure with no charge; try again. |
| `OpenRouter returned no image` | Often a safety block: reword the prompt or use other reference photos. |
| Extra text you did not ask for (for example a German button like "Mehr erfahren") | The style examples can bring in their own text. Check every post before use; pick the other version or run it again. |
| `… did not respond within … seconds` / `did not respond in time` | The image took too long (more likely with many photos of the person). Try again, or raise `IMAGE_TIMEOUT_MS` (e.g. `300000`). |
| `… identity photos are more than the 14 reference images the model accepts` | Lower `IMAGE_IDENTITY_REFS_MAX`. |
| `The logo … has no transparent background` | Put a PNG of the logo with a transparent background in `assets/reference/brand/logo/`, run `uv run ca refs scan` and set `logoFile` in `brand.json` to it. |
| `--source-name "…" is not the publisher of research article …` | Use a short form of the publisher the article names (see `research.md`). |
| `--first-slide … failed the person check` | Make slide 1 again first; a failed slide 1 is never used for the later slides. |
| `Invalid image request: aspect_ratio` | Use one of 1:1, 4:5, 9:16, 16:9. |
| `Failed: …` and exit code 1 | Open the printed folder's `details.json` and read `error`. |
| `rejected x.jpg: too small` | Use a larger photo (512 px short side; logos 256 px). |
| `rejected x.svg` / `x.pdf` | Export it as PNG or JPG and put the image in the set folder. |
| `skipped …: no JPG/PNG/WebP images` | The folder only has PDFs or other files; add images. If it has videos, run `uv run ca refs frames`. |
| `Layout B shows the person, so identity photos are required, but: …` | The person's photos are missing or not scanned. Add them to `assets/reference/identity/person_01/`, run `uv run ca refs scan`, or point `DEFAULT_IDENTITY_SET` / `--set` to the right set. |
| `Layout A shows no person: remove --set …` (or `Format … shows no person`) | That design has no person. Drop `--set` (or `--wardrobe`), or pick a layout or format that shows him. |
| `--format … does not use --…` / `--format … needs --…` | Each format takes only its own texts (see the format table). Remove or add the named option. |
| `Refused: the number "…" is not in research article …` | A stat must be written in the article you name. Use the number exactly as the article has it, or choose another format. |
| `--source … is not a saved research article` | Use an article ID from `research.md` or `uv run ca research digest`. |
| `Only the last carousel slide has a CTA button` / `The last carousel slide needs --cta` | The button belongs on the last slide only. |
| `--headline has more than N words` | Shorten it; each format has its own limit (ad 6, statement 12, news 14, person photo 3). |
| `--aspect for --kind … must be one of: …` | That kind of design has fixed shapes (organic 4:5/1:1, ad 1:1/4:5, story 9:16). |
| `--highlight takes 1-2 words from --headline` / `--sub-highlight must be a word from --subheadline` | The highlight words must appear in the text they belong to. |
| `--icons takes 3-4 labels of 1-2 words each` | Shorten or regroup the icon labels. |
| `Design system not found …` / `design_system.json is invalid; check: …` | Restore `config/design_system.json` (it is in git) or fix the named field. |
| `… needs --set` / `needs --service` | Add the missing option (see `uv run ca refs list` for set names). |
| `… does not use --logo` (or another option) | That workflow ignores the option; remove it or use `social_creative`. |
| `… need --workflow` | `--set`, `--service`, etc. only work together with `--workflow`. |
| `logoFile '…' is not a usable image` | Set `logoFile` in `brand.json` to a file listed in `brand/logo/set.json` as `ok`. |
| `duplicate of y.jpg` | The same photo is in the set twice; one copy is enough. |
| `Set '…' not found` | Run `uv run ca refs scan`, then `uv run ca refs list` to see set names. |
| `brand.json is invalid; check: …` | Fix the named field (colours must look like `#004BA0`). |

## Switching providers

Real images use OpenRouter (see "Set up OpenRouter" above):

```
IMAGE_PROVIDER=openrouter
IMAGE_MODEL=google/gemini-3.1-flash-image
OPENROUTER_API_KEY=<your key>
```

Always run a `--dry-run` first to check the prompt and cost, then run the
command again without `--dry-run`. To go back to free test images, set `IMAGE_PROVIDER=mock`.
Nothing else changes.

For developers: a new provider is one file in `src/content_automation/ai/image/providers/`
(with `create_provider(settings)` and its limits) plus one line in the provider list in
`src/content_automation/ai/image/__init__.py`.

