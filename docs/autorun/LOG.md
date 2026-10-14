# Autorun log — Phases 4–6

Plan: `docs/autorun/AUTORUN-PHASES-4-6.md`. One entry per step (§3.4). A step's commit hash is
filled in by the next step (an entry is committed together with its own step).

## 2026-10-13 15:49 — Phase 4 Step 2.0: D-22/D-23 — DONE
Commit: 1e71ce2   Tests: 240/240
Built: PRD §14 gains D-22 (idea-gate revise from approved; no generation until approved again) and D-23.
Built: AGENTS.md working rules: checks before every commit, `phase <N> step <M>:` commits. CLAUDE.md: Nano Banana decision in Phase 10.
Built: autorun plan moved from the repo root to docs/autorun/ (the plan names that path); this log started.
Decisions: none (D-22 code and its tests follow in Step 2, which lists the D-22 test cases)
Needs review: none

## 2026-10-13 16:08 — Phase 4 Step 2: item commands + manage-items skill — DONE
Commit: 5f7ccee   Tests: 258/258
Built: `ca item list|status|approve|reject|revise|resubmit|history` and `ca audit show` (cli/items.py, thin; --json on list/status/history/audit).
Built: registry gates.py (gate inference per action), approvals.py (approve/reject + decisions), report.py (status report, D-7 mismatches, next actions), list_items, resolve_row (D-12).
Built: D-22 in the status table (approved → revision_requested; generation starts only while the idea is approved); schema migration 2 (items.deliverable).
Built: skill .agents/skills/manage-items/SKILL.md; AGENTS.md phrases + BG ID line; 18 new CLI tests (gate inference, missing reason, multi-ID, alias/row, revise, D-22).
Decisions: B4-1 … B4-9 (PRD "Decisions taken during build")
Needs review: B4-1 generation needs an approved idea everywhere (Step 3 must give make-content items an approved idea); B4-5 exit codes 1/2; B4-6 row numbers via Content ID alias; B4-9 status reads only the mock tracker.

## 2026-10-13 19:03 — Phase 4 Step 3: dry runs, authorizations, jobs, idempotency + wiring — DONE
Commit: 9e45ffd   Tests: 276/276
Built: registry dryruns.py (state/dryruns/DR-….json, expiry, used, scope/cost checks), auth.py (one per provider/unit per dry run, legacy), jobs.py (D-6 key with redo_n, reuse, budget stop, stale, check), progress.py (generation/upload derivation, D-16), runtime.py (scope used by the pipelines), link.py (packages and calendar rows → items); schema migration 3; config/jobs.json; D-2 kinds in config/deliverables.json.
Built: wiring — `ca image`, `ca content build`, `ca calendar generate --build`, `ca video` take `--authorize <dryrun_id>`; run_image_job is a registry job; carousel requests carry jobId (record closes, checks reject + redo, max from the authorization); video agent steps carry jobId (`ca job complete|fail` close); `ca job review --fail` rejects the image job; Drive uploads and tracker writes are jobs; content start/set register items (D-3).
Built: `ca jobs list|check|resume|cancel`, `ca auth list` (cli/jobs.py); skills make-calendar, make-content, make-carousel, make-video, manage-items + AGENTS.md updated (dry-run ID, `--authorize` after "ok", `ca jobs check` before every plugin call).
Built: 18 new tests (reuse/redo, budget stop, unauthorized paid job, stale, check, derivation, dry runs, per-provider authorizations, image job reuse, `ca image` authorize, carousel interrupted + resumed, legacy carousel, agent step, Drive upload jobs).
Decisions: B4-10 … B4-24 (PRD "Decisions taken during build")
Needs review: B4-10 make-content request approves the idea; B4-11 legacy packages approved at build; B4-14 `ca video --authorize` added; B4-15 video credit estimates (client to confirm); B4-16 estimate charged when no actual; B4-22 generated from the pipeline, not "all jobs succeeded"; B4-23 no auto-close of authorizations.

## 2026-10-13 19:15 — Phase 4 Step 4: calendar as a view + migration — DONE
Commit: e277f7a   Tests: 283/283
Built: calendar CSV view: new header (Row, BG ID, …, Status, Version, Package, Content ID), old 9-column header still read; Status from the registry (D-9 mapping); hand-edit guard with a unified diff (written_files, migration 4); `ca calendar sync --week W --discard-edits|--import-edits` (Topic and Planned date only, logged).
Built: `calendar new` registers every row (BG IDs, Content ID aliases); `--replace` rejects the old items ("replaced") and moves the Content ID (D-11); approve/reject through the registry with BG IDs echoed (D-12), `reject --reason`.
Built: `ca registry migrate [--dry-run]` (registry/migrate.py + content/migration.py): calendar CSVs, packages v1/v2, carousel.json, drive_state.json (count only), mock tracker; backup first, oldest first, aliases, §9 mapping, migration_run, old CSVs rewritten; idempotent; created/skipped/unreadable report. Fixtures in tests/fixtures/migration/ (D-18).
Built: real local data, `ca registry migrate --dry-run`: 10 would be created, 0 skipped, 0 unreadable, 1 note (v1 post for Instagram without a deliverable). Skills make-calendar + AGENTS.md updated.
Decisions: B4-25 … B4-33
Needs review: B4-26 calendar reject without a reason still works; B4-29 migration mapping for in-progress/failed parts and v1 deliverables; B4-30 migrated approvals recorded as the user's.

## 2026-10-13 19:24 — Phase 4 Step 5: tracker columns + last-written values + conflict report (mock) — DONE
Commit: 15215fe   Tests: 291/291
Built: registry columns BG ID, Version, Idea/Generation/Review/Upload status, Last updated (config/tracker.json, client to confirm), appended after the existing columns; rows match by BG ID, then Content ID, and the BG ID is filled in (D-13, D-14).
Built: last-written value per cell (registry tracker_cells, migration 5); a hand-edited workflow cell makes its row a conflict (not written, conflict_found logged); tracker_synced per row; manager columns never written.
Built: `ca tracking conflicts [--json]` (hand edits, rows missing on either side, duplicate IDs) and `ca tracking resolve <ID> --keep-sheet|--use-registry`; Drive folder = Content ID else BG ID; mock uploads "uploaded (mock)" (D-16); Drive adapter widens the Sheet (fake Sheets client test).
Decisions: B4-34 … B4-39
Needs review: B4-34 one row per package with several BG IDs; B4-35 registry columns appended at the end; column names (client to confirm).

## 2026-10-13 19:37 — Phase 4 Step 6: finish Phase 4 — DONE
Commit: 29c8926   Tests: 294/294
Built: `ca help commands` (cli/help.py) + test that every AGENTS.md phrase is in it; AGENTS.md skill bullets list their phrases after "Phrases:".
Built: scripts/e2e_phase4.py (+ tests/test_e2e_phase4.py): PRD §10 criteria 1-9 offline on mocks, 9/9 PASS; docs/phases/PHASE-4-E2E.md with the results and the manual Codex Desktop test script.
Built: fixes found by the e2e: calendar commands read the registry view (B4-41), require_budget checks zero-cost paid lines (B4-42), upload_succeeded/failed events (B4-43); BG IDs in show-content, make-video, make-carousel; guide module-5-registry.md; README; PROGRESS Phase 4 summary.
Decisions: B4-40 … B4-44
Needs review: B4-44 design picks are chosen at plan time, so a rebuild after other packages can be a new job (store picks before the provider call?).

## 2026-10-13 19:41 — Phase 5 Step 0: PRD + conflicts — DONE
Commit: fcbbe3b   Tests: 294/294 (no code change)
Built: branch phase-5-research from 29c8926; docs/phases/PHASE-5-PRD.md from autorun §6 (sections and wording copied).
Built: code audit (subagent) → "Conflicts with the current code" C5-1 … C5-21 with the chosen options; PROGRESS Phase 5 checklist.
Decisions: C5-1 … C5-21 (options chosen per §3.2)
Needs review: C5-5 plan-only content types for youtube/podcast/shorts in calendar.json; C5-14 Instagram single graphic off by default; C5-17 content language stays en until the client decides.

## 2026-10-14 15:48 — Phase 5 Step 1: kind idea, sources, claims tables, configs — DONE 85fe0fe
Built: migration 6 (ideas, sources SRC-####, idea_sources, claims CL-####), registry ideas.py/sources.py/strategy.py, config/strategy.json + config/content.json (client to confirm); ideas show "—" for generation/review/upload.
Needs review: strategy pillars, keywords and target shares are a draft.

## 2026-10-14 15:50 — Phase 5 Step 2: newsletter senders, `ca research fetch`, source storage — DONE 4f8de32
Built: config/newsletters.json senders (draft, unverified domains) + fetch limits; research/fetch.py (unwrap tracking links, redirects capped, robots.txt first + final host, size limit, trafilatura); sources saved as research/sources/SRC-####.txt.
Needs review: sender purposes/pillar affinities are a draft (client to confirm).

## 2026-10-14 15:53 — Phase 5 Step 3: sources.json v2, German candidates (disabled), `ca research run` — DONE d2983bd
Built: Source v2 fields (optional; `active` still read), 8 German candidates enabled:false; content/backlog.py (URL/title duplicates merged, keyword pillar guess, off_strategy flag, run counts); `ca research run [--sources] [--newsletters] [--list] [--limit]`.
Needs review: German feed URLs unverified; scraper articles become ideas up to --limit (default 20) per run.

## 2026-10-14 16:05 — Phase 5 Step 4: dedupe, scoring, review queue, manual topics, claims — DONE e0fa281
Built: registry/claims.py (status decided by rules only), score_idea/merge_ideas/review_queue; `ca ideas list|review|add|score|merge`, `ca claims add|list|check`.
Needs review: score weights 40/20/15/15/10 are a draft; a repeated manual topic adds a second note to the older idea.

## 2026-10-14 16:25 — Phase 5 Step 5: calendar v2 — DONE e07ced5
Built: calendar.json `plan` block (plan-only types, slots, targets, pillar tolerance); content/plan.py (`ca calendar plan --week|--month`, inherited approval, shorts +2 days, blocked notes); `ca calendar show --month`; generate skips plan-only rows; `idea:BG-x` sources.
Needs review: draft slot template (10 posts/week, 2 YouTube, 1 carousel, podcast every 2nd week) — client to confirm.

## 2026-10-14 16:50 — Phase 5 Step 6: skills, AGENTS.md, help, e2e — DONE ff9d4d5; PHASE 5 DONE
Built: research-ideas skill; show-content (step 11 backlog) and make-calendar (plan phrases) updated; AGENTS.md + help groups; scripts/e2e_phase5.py 9/9 PASS; full suite 311 passed, mypy --strict 152 files clean.
Needs review: "plan next week" now means `ca calendar plan` (was an alias of `calendar new`); "make calendar next week" keeps the old flow.

## 2026-10-14 17:00 — Phase 6 Step 0: PRD + conflicts — DONE 935521a
Built: docs/phases/PHASE-6-PRD.md (§7 + C6-1..C6-5), PROGRESS Phase 6 checklist; branch phase-6-scripts.
Needs review: C6-1 artifact folder per BG ID inside the package; C6-3 current version may be re-saved.

## 2026-10-14 17:20 — Phase 6 Step 1: formulas, artifacts table, `ca script template` — DONE 06aaeb2 (+ lint/docs follow-up 7ec406f)
Built: config/formulas.json (5 formulas, wpm de 130/en 150, deliverable/kind mapping); migration 7 `artifacts`; registry/artifacts.py; content/scripts.py (models, lineage claims, feedback); `ca script template [--json]`.
Needs review: section word ranges and podcast 10-20 min are a draft (client to confirm).

## 2026-10-14 17:45 — Phase 6 Step 2: check rules, `ca script save|check|show`, markdown — DONE 3712344 (+ typing a6c5606)
Built: content/script_check.py (sections, word ranges, claim refs via lineage, outdated/disputed/unverified, "number without verified source", platform rules); save writes v<current> only; invalid saves logged `artifact_invalid`.
Needs review: disputed claims need a source of each side named in the section notes; any digit counts as a number (BR-07).

## 2026-10-14 18:00 — Phase 6 Step 3: production briefs, `ca brief template|save|check|show` — DONE e3b52b1
Built: content/briefs.py (youtube, podcast, social briefs; sections, thumbnail ≤5 words, caption language, podcast minutes); brief.json + brief.md in v<n>.
Needs review: a brief without a saved script for its version is allowed with a warning.

## 2026-10-14 18:15 — Phase 6 Step 4: social copy onto the formulas — DONE e030af1
Built: content/copy_apply.py — a saved social_graphic/facebook_ad/carousel script fills only its deliverable's brief.json fields (post.headline, captions.<deliverable>, ad.*, carousel.slides); no brief.json or no fit → kept in the script with a warning; packages without a script unchanged.
Needs review: caption mapping expects copy as hook line, 3-5 takeaway lines, question line; ad primary text stays in the script (caption rules differ).

## 2026-10-14 18:40 — Phase 6 Step 5: write-script skill, make-content, AGENTS.md, help, e2e — DONE 4cd19b1; PHASE 6 DONE
Built: write-script skill; make-content step 2b (copy via `ca script save`); AGENTS.md + help group; scripts/e2e_phase6.py 7/7 PASS; full suite 322 passed, mypy --strict 160 files clean.
Needs review: the stricter number rule now applies to copy saved through the formulas (topic packages without claims: no numbers).

## 2026-10-14 18:50 — Autorun finished (§8)
Report: docs/autorun/REPORT-PHASES-4-6.md. Phase 7 not started; nothing pushed or merged.
Needs review: see the report (needs review + client questions).

## P7S1 — fixes, review list/show, regenerate — DONE cd836bb
Needs review: auth auto-closes only when planned jobs succeeded (failed keeps it open); history only from older packages; regenerated v(n+1) lives in the package, v<n> kept in versions/v<n>/; animated-carousel slide redo cost uses image provider.
