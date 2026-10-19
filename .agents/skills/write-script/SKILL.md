---
name: write-script
description: Write a Branded Genius script, social copy or production brief for an item (BG ID) from its editorial formula (config/formulas.json) and only its research claims; `ca` checks, versions and stores it. Use for "write script for BG-x", "write copy for BG-x", "write brief for BG-x", "rewrite script BG-x <feedback>", "show script BG-x", "check script BG-x" and "show brief BG-x". Free; nothing is generated.
---

# Write script

## Rules

- **Only the template's claims.** Every statement comes from the claims `ca script template` lists (with the status `ca` decided). Never invent facts, numbers, quotes, sources or URLs. A number, percent or year needs a verified fact claim in the same section ("number without verified source" otherwise).
- **Thin research:** if the template says "Claims: none" or the claims cannot carry the sections, say so and suggest "research this link …" or "find new ideas" (research-ideas) before writing. Without claims, write without numbers and say so.
- **Unverified claims** (opinions, speculation, one-publisher facts) may be used only when you list them in `acknowledgedUnverified`; tell the user which ones. Outdated claims are never used. A disputed claim needs both sides named in that section's `notes` (a source ID of each side).
- **Language (config/content.json layoutLanguage):** headline, tag, bullets, body and caption in English; the subtitle in German; the CTA in English plus a short German CTA (e.g. "Jetzt folgen", "Mehr erfahren"); the caption ends with one German line. The template prints the rule; the check warns where German is missing. Follow the platform rules it prints (LinkedIn caption 120-250 words, the hook alone on line 1, 3-5 hashtags).
- **Show** a short summary (title, version, words, minutes) and the check result; the full text only when the user asks ("show script BG-x").
- **Versions:** a saved version is never overwritten by a later one. A rewrite after feedback is a new version: `ca item revise` first (only with the user's own words), then the new template, then save.

- **Post copy (social_graphic), the branded card:** `tag` = the pillar category in capitals, 2-3 words ("AI RISK · HR", "AI MISUSE · FINANCE", "AI SOLUTION · MITTELSTAND"); `headline` = 3-7 words, a hook for business owners and decision makers, one highlight word marked like *word*; `subtitle` = German, at most 8 words, the core message; `bullets` = exactly 3 lines, each starting with a verb, at most 6 words, a benefit or action, no quotes, no tool jargon (ATS, CSV, CRM, workflow, lifecycle, pipeline, leverage, synergy: the check refuses them); `icons` = one allowed icon per bullet line (shield-check, search, user-check, alert-triangle, scale, lock, eye, checklist, bulb, chart-line, clock, message-circle, target, users, rocket, file-check); `cta_en` <= 5 words + `cta_de` <= 3 words; `stat` + `stat_label` only with a verified fact claim (then the stat template), else none; `copy` = the caption: a hook line, a short story or insight in plain words, the 3 takeaways, one question, one German line, 3-5 hashtags mixing English and German. Detail lives in the caption, not on the image. The claim and number rules stay as they are.
- **Approval before images:** after the copy is saved, show the user the tag, headline (with its highlight word), German subtitle, the 3 bullets with their icons, the CTA (English and German) and the caption, and wait for their approval before any dry run or image; a change means saving the copy again.

## Write ("write script for BG-x", "write copy for BG-x")

1. `uv run ca script template BG-x --json`: formula, sections with word ranges, platform rules, language, claims, the current version's feedback, `storesIn` and a `skeleton`. Exit code 2: show the message (e.g. shorts and clips get scripts in Phase 9).
2. Fill the skeleton: every section's `text` (within its word range), its `claimRefs`, `notes` where needed, `titleOptions` (YouTube), `cta`, `hashtags` (social), `acknowledgedUnverified`. Social copy (`copy`): the hook on line 1, then 3–5 takeaway lines, then one question line ending in "?" (that shape fills the caption in brief.json). Carousel: `slide_01` cover … `slide_08` a question.
3. Write it to a draft file (e.g. in the scratch folder) and run `uv run ca script save BG-x <file>`. "Not saved": fix every listed problem and save again. Saved: show the summary line, warnings (acknowledged unverified claims) and notes (brief.json fields filled).

## Rewrite ("rewrite script BG-x <feedback>")

1. Only with the user's feedback: `uv run ca item revise BG-x "<their words>"` (a new version).
2. Write steps 1–3 again; the template prints the feedback for the new version. The old version stays as it was.

## Production brief ("write brief for BG-x", "show brief BG-x")

1. `uv run ca brief template BG-x --json` (YouTube: b-roll per section, motion graphics, on-screen text, captions, thumbnail with at most 5 words, chapters, music mood, presenter Roman + setting, assets, editor notes; social: the visual direction).
2. Fill it from the saved script only, write a draft file, `uv run ca brief save BG-x <file>`; fix and save again until "check OK".
3. "show brief BG-x" → `uv run ca brief show BG-x`.

## Show and check

- "show script BG-x" → `uv run ca script show BG-x [--version N]` (the Markdown).
- "check script BG-x" → `uv run ca script check BG-x`: checks the saved script again (claims may have aged); report the problems.
