# Pre-Codex check

Run on 2026-10-03 with free checks only: dry runs and simulated history (no real images or
videos, no paid calls), in a scratch folder, not in `outputs/`. The check script is not part of
the project; repeat the checks with the commands in the guides.

Result: **41 of 41 passed.**

| Check | Result | Details |
| --- | --- | --- |
| format ad (layout B) | PASS | person=yes, identity 9, logo 1, style 3, refs 13/14, cost $0.101 |
| format statement | PASS | person=no, identity 0, logo 1, style 0, refs 1/14, cost $0.101 |
| format stat | PASS | person=no, identity 0, logo 1, style 0, refs 1/14, cost $0.101 |
| format news (with person) | PASS | person=yes, identity 9, logo 1, style 0, refs 10/14, cost $0.101 |
| format news (no person) | PASS | person=no, identity 0, logo 1, style 0, refs 1/14, cost $0.101 |
| format carousel slide 1/5 | PASS | person=yes, identity 9, logo 1, style 3, refs 13/14, cost $0.101 |
| format carousel slide 2/5 | PASS | person=no, identity 0, logo 1, style 3, refs 4/14, cost $0.101 |
| format carousel slide 3/5 | PASS | person=no, identity 0, logo 1, style 3, refs 4/14, cost $0.101 |
| format carousel slide 4/5 | PASS | person=no, identity 0, logo 1, style 3, refs 4/14, cost $0.101 |
| format carousel slide 5/5 | PASS | person=no, identity 0, logo 1, style 3, refs 4/14, cost $0.101 |
| format person_photo | PASS | person=yes, identity 9, logo 1, style 0, refs 10/14, cost $0.101 |
| format checklist | PASS | person=no, identity 0, logo 1, style 0, refs 1/14, cost $0.101 |
| required fields (ad without subheadline/cta) | PASS | --format ad needs --subheadline, --cta. |
| CTA only in ad / last slide (statement + cta refused) | PASS | --format statement does not use --cta. |
| stat not in research refused | PASS | w to use vector embeddings in AEO"). A stat must come from the research; never invent one. |
| deliverable facebook_post (fb post) | PASS | facebook_post: 1 image x 4:5 2K (format statement), "Every unanswered question costs a lead."; picked: scene office_night, decor light_streaks; no person, 0 identity + 0 style photos + logo, via openrouter: about $0.101 |
| deliverable facebook_ad (facebook ad) | PASS | facebook_ad: 3 images x 4:5 2K (format ad, layout B), "Answer Every Website Visitor"; picked: scene home_desk, wardrobe navy_suit, props laptop_coffee, decor light_streaks, holograms node_network, pose arms_crossed; the man shown, |
| deliverable instagram_carousel (insta post) | PASS | instagram_carousel: 5 of 5 slides x 4:5 2K (format carousel), "Answer Every Website Visitor"; picked: scene coworking, wardrobe oxford_shirt, decor line_frames, pose arms_crossed; the man shown, 9 identity + 3 style photos + logo, |
| deliverable reel_short (reel) | PASS | reel_short: 1 video, 2 scenes, 10 s, 9:16; video scenes via higgsfield-plugin; cost: Higgsfield/HeyGen credits charged in those apps (not estimated by this tool; check the plan or credit balance there) |
| deliverable ugc_ad (ugc ad) | PASS | ugc_ad: 1 video, 2 scenes, 10 s, 9:16; video scenes via higgsfield-plugin; cost: Higgsfield/HeyGen credits charged in those apps (not estimated by this tool; check the plan or credit balance there) |
| deliverable podcast_clip (podcast clip) | PASS | podcast_clip: 1 video, 2 scenes, 17 s, 9:16; avatar scenes via heygen-plugin, video scenes via higgsfield-plugin; cost: Higgsfield/HeyGen credits charged in those apps (not estimated by this tool; check the plan or credit balance  |
| strict: 'facebook ad only' builds only facebook_ad | PASS | deliverables ['facebook_ad'], parts ['ad'] |
| strict: 'post' asks | PASS | Ask the user, never guess: "post" is ambiguous: it could be facebook post (facebook_post) or insta post (insta |
| strict: 'ad' asks | PASS | Ask the user, never guess: "ad" is ambiguous: it could be facebook ad (facebook_ad) or ugc ad (ugc_ad). Known  |
| strict: 'linkedin post' asks | PASS | Ask the user, never guess: "linkedin post" is not a deliverable we make. Known names: facebook_post: facebook  |
| strict: no deliverables builds nothing | PASS | No deliverables on this package yet: nothing is built. Ask the user what to make, then run: uv run ca content  |
| newsletter sample -> package -> set -> brief -> dry-run | PASS | Estimated image cost: $0.808 (openrouter). Run again without --dry-run to build. |
| variety: two packages in a row differ | PASS | formats ['statement', 'stat']; picks ['scene office_night, decor light_streaks', 'scene office_day, decor arc_lines'] |
| quality: a good carousel brief passes | PASS | Estimated image cost: $0.505 (openrouter). Run again without --dry-run to build. |
| quality: hook with tip content refused | PASS | - carousel.slides[1] is the hook: it names the problem or the promise and carries no tip (no tip text, visual, chat or d |
| quality: two tips with the same point refused | PASS | - carousel.slides[2] and slides[3] make the same point: give each tip its own idea |
| quality: tip without a how refused | PASS | - carousel.slides[4]: give the concrete how or an example in subheadline, or show it with a chat or diagram |
| quality: Instagram 'Learn more' CTA refused | PASS | - carousel.slides[5].cta "Learn more": Ask for a comment with one keyword, a save, or a DM; never a "Learn more" button. |
| quality: hook without audience refused | PASS | - carousel.audienceLine: the hook names the audience, e.g. "FOR DENTAL PRACTICES" |
| proof: invented result number refused | PASS | - captions.instagram_carousel: "3x" reads as a result; cite results only from docs/company/proof.md (or a stat with its research s |
| scene: relevant to the topic, then rotated | PASS | dental practice posts got scenes ['clinic', 'clinic', 'clinic'] |
| scene rotation among relevant scenes (history simulated) | PASS | dental topic: clinic used -> reception_desk; reception_desk used -> clinic; an unrelated topic falls back to the full pool |
| carousel slides 2+ attach slide 1 (`--first-slide`, mock placeholder slide 1) | PASS | slide 1 attached as a SERIES ref after the demo style refs; refused on the hook slide (checked in the previous build, code unchanged) |
| video requests (plugin providers, request files only) | PASS | Higgsfield plugin, all identity photos + person rule, no retries (previous build, code unchanged) |
| skills: frontmatter, triggers, STOP before every cost, no tool names, no secrets | PASS | make-content gained the content-quality rules; doctor finds all 3 skills |
| lint (ruff) and type-check (mypy src) | PASS | all checks passed; no issues in 65 source files |

What each design dry run verified: the person rule (identity photos and "He is the only person"
when he is shown; 0 identity photos and "No people, faces or human figures" when not), at most
14 reference images, the logo attached, colours and fonts from `brand.json`, the headline in the
brand heading font ("never condensed"), the fill-the-canvas rule, the website footer, the audience
line where required, chat and diagram texts listed exactly, the "render only the listed texts"
rule, and a cost line.

Content checks in the brief (the dry run refuses): a carousel hook without an audience line or
with tip content; two tips that make the same point; a tip without its how (or a chat/diagram);
a last-slide CTA that does not fit the platform (Instagram: comment, save or DM, never "Learn
more"; Facebook: the link in the caption); result-like numbers (%, x, money, counts of leads,
bookings ...) that are not in `docs/company/proof.md` or the cited research.

## Known

- `docs/company/services.md` has no `Offer:` line yet, so the brief template asks for the offer
  instead of filling it. Add one line (`Offer: ...`) with the real offer.
- `docs/company/proof.md` lists one result, copied from the Proof line in services.md (4.9 rating
  from 9 Google reviews). Add more only if they are real.
- Old package whose brief no longer validates: `outputs/content/2026-10-01_ai-chatbots-for-lead-generation`.
- Identical requests get identical picks on purpose (the dry run shows what the build will use);
  scenes rotate among the relevant ones as packages are built.
- With the mock image provider only 4 identity photos are sent (its limit); OpenRouter sends all 9.

## What only Codex can verify

- **Gmail plugin**: installed, finds the `Newsletters` label and the last 7 days, read-only use.
- **Higgsfield plugin**: installed, makes 9:16 clips, and whether it accepts the identity photos as
  reference images (if not, Codex must stop and ask for shots with a person).
- **HeyGen plugin**: installed, lists the avatars, uses the person's own avatar (`HEYGEN_AVATAR_ID`
  is not set yet).
- **Real output**: the same person in real images and videos; the heading font not condensed;
  chat bubbles, diagram labels, audience line and footer rendered exactly and readable on a phone;
  no large empty areas.
- That Codex finds the skills in `.agents/skills/` and that web search is available for thin topics.
- Real costs (`actualCostUsd`, plugin credits).
