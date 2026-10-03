# Pre-Codex check

Run on 2026-10-03 with free checks only: dry runs, one mock placeholder slide and one video job
that wrote request files (no real images or videos, no paid calls). Everything ran in a scratch
folder, not in `outputs/`. The script is not part of the project; repeat the checks with the
commands in the guides.

Result: **37 of 37 passed.**

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
| deliverable facebook_post (fb post) | PASS | facebook_post: 1 image x 4:5 2K (format statement), "Every unanswered question costs a lead."; picked: scene abstract_gradient, decor light_streaks; no person, 0 identity + 0 style photos + logo, via openrouter: about $0.101 |
| deliverable facebook_ad (facebook ad) | PASS | facebook_ad: 3 images x 4:5 2K (format ad, layout B), "Answer Every Website Visitor"; picked: scene home_desk, wardrobe navy_suit, props laptop_coffee, decor light_streaks, holograms node_network, pose arms_crossed; the man shown, |
| deliverable instagram_carousel (insta post) | PASS | instagram_carousel: 5 of 5 slides x 4:5 2K (format carousel), "Answer Every Website Visitor"; picked: scene conference_stage, wardrobe oxford_shirt, decor line_frames, pose arms_crossed; the man shown, 9 identity + 3 style photos  |
| deliverable reel_short (reel) | PASS | reel_short: 1 video, 2 scenes, 10 s, 9:16; video scenes via higgsfield-plugin; cost: Higgsfield/HeyGen credits charged in those apps (not estimated by this tool; check the plan or credit balance there) |
| deliverable ugc_ad (ugc ad) | PASS | ugc_ad: 1 video, 2 scenes, 10 s, 9:16; video scenes via higgsfield-plugin; cost: Higgsfield/HeyGen credits charged in those apps (not estimated by this tool; check the plan or credit balance there) |
| deliverable podcast_clip (podcast clip) | PASS | podcast_clip: 1 video, 2 scenes, 17 s, 9:16; avatar scenes via heygen-plugin, video scenes via higgsfield-plugin; cost: Higgsfield/HeyGen credits charged in those apps (not estimated by this tool; check the plan or credit balance  |
| strict: 'facebook ad only' builds only facebook_ad | PASS | deliverables ['facebook_ad'], parts ['ad'] |
| strict: 'post' asks | PASS | Ask the user, never guess: "post" is ambiguous: it could be facebook post (facebook_post) or insta post (insta |
| strict: 'ad' asks | PASS | Ask the user, never guess: "ad" is ambiguous: it could be facebook ad (facebook_ad) or ugc ad (ugc_ad). Known  |
| strict: 'linkedin post' asks | PASS | Ask the user, never guess: "linkedin post" is not a deliverable we make. Known names: facebook_post: facebook  |
| strict: no deliverables builds nothing | PASS | No deliverables on this package yet: nothing is built. Ask the user what to make, then run: uv run ca content  |
| newsletter sample -> package -> set -> brief -> dry-run | PASS | Estimated image cost: $0.808 (openrouter). Run again without --dry-run to build. |
| variety: two packages in a row differ | PASS | formats ['statement', 'stat']; picks ['scene abstract_gradient, decor light_streaks', 'scene conference_stage, decor arc_lines'] |
| carousel slides 2+ attach slide 1 (`--first-slide`, mock placeholder slide 1) | PASS | slide 2: 3 demo style refs + slide 1 as SERIES ref, no person; refused on the hook slide |
| video requests (reel_short, plugin providers, request files only) | PASS | Higgsfield plugin, 9 identity photos + person rule, no retries; details.json identitySet + 9 identityAssetIds |
| video with mock/none provider | PASS | job created and held: "draft — video pending" with the exact .env lines (checked in the deliverables build) |
| skills: frontmatter, triggers | PASS | doctor: 3 found (show-content, make-content, make-video); each description names its trigger phrases |
| skills: STOP before every cost | PASS | show-content stops for a pick; make-content stops after stage 1 and before building; make-video stops for "ok" |
| skills: no hardcoded tool names, no secrets | PASS | plugins are found at run time; grep found no tool names or keys |
| MCP wording removed | PASS | none left in AGENTS.md, docs, skills or src (.mcp.json, the Claude Code config, is unchanged) |
| lint (ruff) and type-check (mypy src) | PASS | all checks passed; no issues in 64 source files |
| `ca doctor` | PASS | 0 problems, 1 warning (HEYGEN_AVATAR_ID not set); reports skills, deliverables, design system, image/video/avatar providers, daily limit 30, all 9 identity photos per image |

What each design dry run verified: the person rule (identity photos and "He is the only person"
when he is shown; 0 identity photos and "No people, faces or human figures" when not), at most
14 reference images, the logo attached, colours and fonts taken from `brand.json`, the
"render only the listed texts" rule, and a cost line.

## Known

- Old package whose brief no longer validates: `outputs/content/2026-10-01_ai-chatbots-for-lead-generation`
  (written before the design system: `withPerson`, a plain-text caption, no `link`). Rewrite its
  brief from a new template, or leave it as it is (its images are done).
- Identical requests get identical picks on purpose (the dry run shows what the build will use);
  different posts, and every new package after the last one, rotate.
- With the mock image provider only 4 identity photos are sent (its limit); OpenRouter sends all 9.
- The video cost is not estimated by the tool: Codex shows what the plugin reports before it
  generates.

## What only Codex can verify

- **Gmail plugin**: that it is installed, finds the `Newsletters` label and the last 7 days, and
  that the skill only reads (never sends, deletes, archives or labels).
- **Higgsfield plugin**: that it is installed, makes 9:16 clips from a prompt or a start image,
  and whether it accepts the identity photos as reference images (if not, Codex must stop and ask
  for shots with a person).
- **HeyGen plugin**: that it is installed, lists the avatars, and makes clips with the person's own
  avatar (`HEYGEN_AVATAR_ID` is not set yet).
- **Real likeness**: that real images and videos really show the same person (only visible in
  real output).
- That Codex finds the skills in `.agents/skills/` (AGENTS.md also points to them) and that web
  search is available for thin topics.
- Real text rendering and real costs (`actualCostUsd`, plugin credits).
