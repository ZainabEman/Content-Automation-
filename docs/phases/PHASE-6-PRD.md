# Phase 6 PRD — Editorial formulas, scripts and production briefs (v3 spec)
Branch: phase-6-scripts (from phase-5-research, ff9d4d5). Date: 14 Oct 2026. Source: docs/autorun/AUTORUN-PHASES-4-6.md §7.

## 1. Goal
Every content item can get formula-based copy or a script plus a production brief:
- written by Codex
- built only from the item's research claims
- validated and versioned by `ca`

## 2. Spec coverage
UC-08 (scripts and production briefs), editorial formulas, BR-03, BR-06, BR-07, BR-09.

## 3. Out of scope
- recording, editing and production statuses (Phase 8)
- the review command and review-gated upload (Phase 7)
- image/video generation changes
- Shorts/Opus clip scripts (Phase 9)
- translation beyond `config/content.json`

## 4. Decisions
- **P6-D1 Who writes:** Codex writes the text in the skill; `ca` gives it the template and validates the result. First audit how copy is produced today (content.md, brief.template.json, post.md, carousel slides) and follow that pattern.
- **P6-D2 Formulas in `config/formulas.json`:**
  - `youtube_longform`: hook, german_problem, ai_risk_or_mistake, why_it_happens, correct_ai_solution, cta_outro. Target 8–12 min; words per minute in config (de 130, en 150).
  - `podcast`: warning, critical_situation, why_it_matters, what_could_go_wrong, correct_response. Duration in config.
  - `social_graphic`: central_message, audience, purpose educational|promotional|campaign, headline, copy, visual_direction, cta. Platform rules: LinkedIn 120–250 words, hook in the first line, 3–5 hashtags; existing Facebook and Instagram rules.
  - `carousel`: 8 slides mapped to the formula, with the last slide ending in a question (matches Phase 3).
  - `facebook_ad`: primary text, headline, description, CTA.
- **P6-D3 Artifacts:**
  - A registry table `artifacts`: item, version, type script|brief|copy, path, check result, created_at.
  - Files live in `<package>/scripts/v<n>/` as `script.json` + a rendered `script.md`, and `brief.json` + `brief.md`.
  - Old versions are never overwritten.
- **P6-D4 Script JSON:**
  - item, version, formula, language
  - sections [{key, text, claim_refs[], notes}]
  - title_options, cta, `acknowledged_unverified[]`
  - word count and duration estimate (computed)
- **P6-D5 Brief JSON:**
  - **YouTube:** b_roll [{section, description, source_hint stock|screen|own_footage|ai_generated}], motion_graphics, on_screen_text, captions {style, language}, thumbnail {concept, text ≤ 5 words}, chapters, music_mood, presenter (Roman) + setting, assets_needed, editor_notes.
  - **Podcast:** recording_source roman|heygen|higgsfield (field only), segments with timing, show notes, episode title and description.
  - **Social:** visual direction for the existing image pipeline.
- **P6-D6 Validation (`ca script check`) is mechanical:**
  - every formula section is present and non-empty
  - word counts are within range
  - every claim_ref exists and belongs to the item's (or parent idea's) research
  - outdated claims → error
  - a disputed claim must cite both sides
  - unverified or speculation claims → error unless they are listed in `acknowledged_unverified` (shown to the user)
  - any number, percent or year in a section's text needs at least one verified fact claim_ref in that section, otherwise error "number without verified source" (BR-07)
  - platform rules (length, hashtags)
  - Results are stored on the artifact and logged as `artifact_saved` / `artifact_invalid`.
- **P6-D7 Revisions:**
  - `ca script template` includes the current version's feedback (from revise).
  - Rewriting a script after feedback = `ca item revise` → a template for the new version → save into `v<n+1>`.
- **P6-D8 Existing copy:** LinkedIn/Facebook post copy, carousel slides and ad copy move to the social_graphic/carousel/facebook_ad formulas with claim refs. The existing outputs (post.md, slide text used by the overlay) stay compatible, and old packages still render.

## 5. Commands
| Command | Codex phrase |
|---|---|
| `ca script template BG-x [--json]` (skeleton, claims with status, feedback, platform rules, language) | (used by the skill) |
| `ca script save BG-x <file>` (validate, store, render md) | (used by the skill) |
| `ca script check BG-x` | "check script BG-x" |
| `ca script show BG-x [--version]` | "show script BG-x" |
| `ca brief template/save/check/show BG-x` | "write brief for BG-x", "show brief BG-x" |

## 6. Skills
**New `write-script` skill:**
- Phrases: "write script for BG-x", "write copy for BG-x", "write brief for BG-x", "rewrite script BG-x <feedback>" (revise first), "show script BG-x".
- Rules:
  - use only the claims from the template
  - never invent facts, numbers, quotes or sources
  - if research is thin, say so and suggest "research this link …" / "find new ideas"
  - show a short summary plus the check result, and the full text only on request

**Update `make-content`** so post, carousel and ad copy goes through the template/save path.

## 7. Acceptance criteria (offline)
1. Templates exist for every formula and include the claims and the feedback.
2. A valid YouTube script fixture saves as v1 with md rendered and a duration estimate.
3. A missing section, a number without a verified source, an outdated claim, or an unacknowledged unverified claim each fail with a clear message.
4. A revise then a new save creates v2, and v1 is unchanged.
5. Podcast and YouTube briefs validate and render.
6. LinkedIn copy outside 120–250 words fails.
7. Existing post and carousel builds still work on mock, and old packages still render.
8. All checks pass.

## 8. Build steps
0. PRD + conflicts.
1. `config/formulas.json`, JSON schemas, the artifacts table, `ca script template`.
2. Validation rules, `save/check/show`, the md renderer.
3. YouTube and podcast briefs (`ca brief …`).
4. Move post, carousel and ad copy onto the formulas (keeping compatibility).
5. The write-script skill, make-content update, AGENTS.md, help, `scripts/e2e_phase6.py`, PHASE-6-E2E.md (with the Codex test script), PROGRESS.


## Conflicts with the current code
- C6-1 One package holds several items (Phase 4 D-1), and ideas and plan-only rows have no package. → Artifacts go to `<package>/scripts/<BG-x>/v<n>/`, or `<OUTPUT_DIR>/items/<BG-x>/scripts/v<n>/` when the item has no package (instead of `<package>/scripts/v<n>/`).
- C6-2 `brief.json` already names a package's image/caption brief. → The production brief is `scripts/<BG-x>/v<n>/brief.json` + `brief.md` (never the package root's file); docs call it the "production brief".
- C6-3 Versions come from the registry (`ca item revise` bumps the item's version). → `save` writes into v<current version>; saving the current version again replaces its files (each save is a new `artifacts` row); lower versions are never written. An invalid save writes nothing into v<n>: it is logged `artifact_invalid` with the problems and exits 1.
- C6-4 Claims live on ideas (Phase 5); content items are their children (shorts: grandchildren). → A claim_ref may belong to the item or any ancestor up to its idea.
- C6-5 Post, ad and carousel copy lives in the package's brief.json (`captions`, `ad`, `carousel.slides`), which build and the overlay read. → `ca script save` for a social item validates the formula and, when the item's package has a brief.json, writes the copy into those fields; packages without a script build and render as before (P6-D8).
