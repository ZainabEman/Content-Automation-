# Pre-Codex check

Run on 2026-10-04 with free checks only: dry runs with the OpenRouter settings (no key used, no
call) and mock builds in a scratch folder, not in `outputs/`. No real images or videos, no paid
calls. The check script is not part of the project; repeat the checks with the commands in the
guides.

Result: **30 of 30 passed** (this round: person consistency, logo, source line, HeyGen voice),
plus ruff and mypy clean (66 source files) and the existing tests of the changed modules (52
passed).

## Diagnosis that led to this round

Package `outputs/content/2026-10-03_automated-lead-follow-up-for-real-estate`, carousel slide 1:

- **Attached, in order**: images 1–9 = the 9 photos of `identity/person_01`, primary first (1, 2,
  6, 7, then 3, 4, 5, 8, 9): correct. Image 10 = the logo `brand/logo/cFkuqb.jpg` (the wordmark
  on a white background, no transparency). Images 11–13 = style frames carousel_09 `day 10..1_2`
  (outline human figures, no logo), carousel_01 `No 1__2` (a human hand reaching to a robot
  hand, no logo), carousel_02 `no 1_2` (no person, no logo).
- **Logo**: none of the style frames shows a logo, and the logo file was right; the model ignored
  image 10 and invented a "brand" mark with a hexagon icon. The prompt asked it to draw the logo.
- **Person**: no style frame shows a face, so the face did not come from them. The model drifted
  to a generic man (fuller side-parted hair, stubble, younger) despite the identity rules.
  Contributing: 13 reference images, two style frames with human figures, a long design prompt.
- **Scene**: no scene tag matched "real estate", so the rotation picked `reception_desk`
  ("a bright practice or office"), which read as a clinic.

## Results

| Check | Result | Details |
| --- | --- | --- |
| format ad (layout B) | PASS | person=yes, identity 9, style 0 (none), refs 9/14, logo pasted (not sent), scene property_exterior |
| format ad (layout A) | PASS | person=no, identity 0, style 0 (none), refs 0/14, logo pasted (not sent), scene property_exterior |
| format statement | PASS | person=no, identity 0, style 0 (none), refs 0/14, logo pasted (not sent), scene property_exterior |
| format stat | PASS | person=no, identity 0, style 0 (none), refs 0/14, logo pasted (not sent), scene property_exterior |
| format news (with person) | PASS | person=yes, identity 9, style 0 (none), refs 9/14, logo pasted (not sent), scene real_estate_office |
| format carousel slide 1/5 | PASS | person=yes, identity 9, style 3 (all people/logo-free), refs 12/14, logo pasted (not sent), scene property_exterior |
| format carousel slide 3/5 | PASS | person=no, identity 0, style 3 (all people/logo-free), refs 3/14, logo pasted (not sent), scene property_exterior |
| format carousel slide 5/5 | PASS | person=no, identity 0, style 0 (none), refs 0/14, logo pasted (not sent), scene property_exterior |
| format person_photo | PASS | person=yes, identity 9, style 0 (none), refs 9/14, logo pasted (not sent), scene real_estate_office |
| format checklist | PASS | person=no, identity 0, style 0 (none), refs 0/14, logo pasted (not sent), scene office_day |
| stat: source line from the brief | PASS | prompt lists - Source line: "Source: Zillow" |
| stat: source line without sourceName | PASS | defaults to the article's source: Zillow Premier Agent |
| stat: wrong publisher refused | PASS | --source-name "Forbes" is not the publisher of research article a94cc37798ebb3af ("Zillow Premier Agent") |
| scene: real estate topic | PASS | real_estate_office (the three real estate scenes and office_day are the relevant ones) |
| scene: dental topic still clinic/reception | PASS | reception_desk |
| scene: unrelated topic never a trade scene | PASS | office_night (clinic, reception, shop and real estate scenes only when the topic names them) |
| style tags stored in set.json | PASS | 318 style images, 0 untagged (197 neither, 51 people, 62 logo) |
| logo: JPG without transparency refused | PASS | cFkuqb.jpg -> "has no transparent background ... supply a PNG" |
| logo: brand.json logoFile is a transparent PNG | PASS | logo (1).png, trimmed to its alpha box |
| person check: build stops after slide 1 | PASS | carousel review, files ['images/carousel-1.png']; post done |
| person check: unrecorded -> nothing made | PASS | same job IDs; prints the check again |
| person check: fail -> slide 1 made again | PASS | a new job for slide 1; the fail stays in the first job's details.json |
| failed slide 1 never used for later slides | PASS | --first-slide with a failed slide 1 is refused |
| person check: pass -> slides 2-5, slide 1 without logo | PASS | carousel done, 5 files; slides 2-5 attach slide 1's raw/image-1.png |
| HeyGen voice missing -> no video job | PASS | reel pending: "HeyGen avatar or voice ID not set"; no job folder; asks for ca env set |
| video dry run per scene: provider, avatar, voice, duration, credits | PASS | scene 1: avatar, 12 s, heygen-plugin, avatar fe2710…, voice NOT SET, credits: reported by the HeyGen plugin before generating |
| ad with the man: one job per variant, check after each | PASS | ad review after variant 1 of 3 |
| HeyGen request passes the voice explicitly | PASS | options avatarId + voiceId; step 2 says never rely on the default voice |
| ca env set: one allowed line only, file never shown | PASS | HEYGEN_VOICE_ID set; a key name is refused |
| doctor: voice warning, logo, style tags | PASS | [WARN] HEYGEN_VOICE_ID not set; [ OK ] Logo: brand/logo/logo (1).png; style examples all tagged |

What each design dry run verified: the logo is not sent and the prompt says "Do not draw any
logo" and keeps the top-right corner empty; style images never carry a logo, and with the man
only people-free, logo-free ones; 9 identity photos first when he is shown ("the only person
allowed ... any person, face, body part or logo in any other reference image is ignored"), "No
people" when not; "No readable text in the scene" on every design; at most 14 reference images.

Still valid from the 2026-10-03 run (code unchanged): strict deliverable selection, the
newsletter-to-package flow, the content-quality refusals (hook, tips, platform CTA, proof
numbers), variety between packages, and the plugin video requests.

## Known

- **Ads have no style examples now**: all 6 past ads show the logo (4 also show people), so none
  is sent. Add logo-free (and, for ads with the man, people-free) ad examples to
  `assets/reference/creative/facebook_ads/`, rescan, and tag them.
- Carousel CTA slides get no style example either (every demo CTA slide shows the logo); they
  still attach slide 1 for a consistent look.
- `brand.json` `logoFile` was changed from `cFkuqb.jpg` (white background) to `logo (1).png`,
  the transparent version of the same wordmark. An automatic cut-out of the JPG was tried and
  rejected: the white highlights inside the silver "GENIUS" letters became transparent.
- `HEYGEN_VOICE_ID` is not set yet, so the podcast clip of the real estate package will not
  start until it is chosen. Its earlier job (`2326_automated-lead-follow-up-for-real-estate`)
  failed with HeyGen "voice_id is required"; the next build reports that failure, the one after
  starts a new job.
- The existing real estate package still has its old slide 1 (wrong person, invented logo):
  rebuild it after this change (costs apply).
- `docs/company/services.md` has no `Offer:` line yet; `docs/company/proof.md` lists one result.
- Old package whose brief no longer validates: `outputs/content/2026-10-01_ai-chatbots-for-lead-generation`.
- With the mock image provider only 4 identity photos are sent (its limit); OpenRouter sends all 9.

## What only Codex can verify

- **Person check**: that Codex views each image with the man beside two primary photos, records
  `ca job review`, and stops to ask before regenerating.
- **Real output**: the same person in real images and videos; the top-right corner empty (no
  invented logo under the pasted one); no readable text on screens and signs; the source line on
  stat posts.
- **Gmail plugin**: installed, finds the `Newsletters` label and the last 7 days, read-only use.
- **Higgsfield plugin**: installed, makes 9:16 clips, and whether it accepts the identity photos as
  reference images (if not, Codex must stop and ask for shots with a person).
- **HeyGen plugin**: lists avatars and voices (own or cloned first), confirms that both IDs
  exist before the "ok", and makes clips with the voice passed explicitly.
- Real costs (`actualCostUsd`, plugin credits).
