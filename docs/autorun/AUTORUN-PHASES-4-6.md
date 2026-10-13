# AUTORUN — Phase 4 (rest), Phase 5, Phase 6
Branded Genius Content Automation. Written 13 Oct 2026. Save in the repo as `docs/autorun/AUTORUN-PHASES-4-6.md`.

---

## 0. How Claude Code uses this file
- Work through §5 (Phase 4), then §6 (Phase 5), then §7 (Phase 6), step by step, **without waiting for the user between steps**.
- Before every step, re-read §2–§4 and that step's section. After every step, append an entry to `docs/autorun/LOG.md` (format in §3.4).
- **Resuming:** if a session ends or the context is compacted, read §0–§4 and `docs/autorun/LOG.md`, then continue at the first step not marked done. Never redo a committed step.
- Stop **only** for a stop condition in §3.3. Otherwise decide using §3.2, record the decision, and keep going.
- Use subagents (the Task tool) for broad code searches or audits, so the main context stays small.
- Never print whole files in replies. Keep chat output to short progress lines.

---

## 1. Project context (what you need to know)

### 1.1 The system
- A content-production system for **Branded Genius**, a German company. The lead is **Roman**.
- **One user** controls everything through natural-language commands in **Codex Desktop** (the orchestrator).
- Codex runs project skills (`.agents/skills/<name>/SKILL.md`, mapped to phrases in `AGENTS.md`). The skills call the Python Typer CLI **`ca`** (`cli/`) and Codex plugins (Gmail, Higgsfield, HeyGen, Google Drive).
- `ca` **cannot** call plugins. Plugin calls happen inside skills, and `ca` records their results.
- You (Claude Code) are the developer.
- Workflow from the client spec: **Command → Research → Generate → Review → Approve → Produce → Store → Track → Publish**, with human approval gates and spending authorization.

### 1.2 Client spec v3 (the requirements)
**Platforms:** YouTube long-form, YouTube Shorts, LinkedIn, Instagram, Facebook (+ ad creatives), TikTok, podcasts.

**Strategy (BR-02):** real problems in German society, AI risks, AI misuse, AI mistakes, and appropriate AI solutions.

**Editorial formulas:**
- YouTube: current German problem → AI risk or mistake → why it happens → correct AI solution.
- Podcast: warning → critical situation → why it matters → what could go wrong → correct response.
- Graphics/social: central message, audience, purpose (educational/promotional/campaign), headline, copy, visual direction, CTA.

**Monthly targets:**
- 8 YouTube long-form videos
- 10–12 Opus Pro candidate clips per video → 4–5 selected (32–40 clips/month)
- 1–2 graphics/day (30–60/month)
- all scheduled podcasts
- 100% of final content reviewed before publishing

**Business rules:**
- **BR-01:** single command interface
- **BR-03:** traceability (idea → research → assets → deliverables)
- **BR-04:** approval gates
- **BR-05:** spending authorization per scope, never unlimited
- **BR-06:** brand consistency
- **BR-07:** never fabricate facts, sources, approvals, costs or successes
- **BR-08:** protect manual tracker edits
- **BR-09:** versions
- **BR-10:** no duplicates
- **BR-11:** separate statuses (idea, generation, editorial review, upload, publication)
- **BR-12:** honest errors
- **BR-13:** publish only approved content via an authorized integration
- **BR-14:** honest target counts
- **BR-15:** no silent scope or provider changes

**Non-functional requirements:** persistent state, resume, no duplicate paid operations or uploads, secrets kept out of all output, audit log, replaceable providers, stable IDs.

### 1.3 Environment
- The user's PC: Windows 10, 2-core CPU, 8 GB RAM, no GPU.
- Always use `uv run …` and `pathlib`. No bash-only scripts; any helper script is Python.
- Required checks: ruff, `mypy --strict`, pytest (offline).

### 1.4 What exists (Phases 1–3 + Phase 4 so far)
**Calendar** (`content/calendar.py`, `calendar/<YYYY-Www>.csv`):
- Mon LinkedIn, Tue Facebook, Wed LinkedIn, Thu Facebook, Fri Instagram carousel.
- Statuses Proposed/Approved/Rejected/Generated.
- `generate` = free stage 1 → one combined dry run → "ok" → build.
- Content IDs `<week>-<row:02>`.

**Packages:** `outputs/content/YYYY-MM-DD_<slug>/` holds research.md, content.md, brief(.template).json, package.json, post.md, images/, video/ and carousel/.

**Images:**
- `ai/image` `generate_image()`, with providers openrouter, mock, comfyui and runpod.
- The app renders all text and the logo itself (`text_overlay.py`, Jost font).
- LoRA/ComfyUI work is **parked**: don't touch it.

**Carousel (Phase 3):**
- 8 slides, 1080², 5 s, 24 fps, Higgsfield plugin.
- Request files → skill → `ca carousel record` → checks → `ca carousel render` → Drive → tracker.
- Resumable via `carousel/carousel.json` and `ca carousel continue`. Local animation is the fallback.

**Drive and tracker:**
- `storage/` (`drive_api.py`, `mock.py`; `STORAGE_PROVIDER=mock|drive`).
- Tracker: Google Sheet or mock `outputs/drive/Content Automation/tracking.csv`, keyed by Content ID. Manager-owned columns: Approval status, Publishing status, Publication date.
- **Google Cloud is not set up**, so everything runs on mock.

**Gmail:** only brandedgenius.de@gmail.com, label `Newsletters`, 30-day window (`config/newsletters.json`). No per-newsletter purpose yet.

**Newsletters:** Marketing Brew (morningbrew.com), Content Marketing Institute (contentmarketinginstitute.com), Marketing AI Institute (marketingaiinstitute.com), Search Engine Land (searchengineland.com), Later (later.com). The domains are unverified, and these newsletters fit the new strategy only partly.

**Scraper:** `config/sources.json` lists US marketing sites; output goes to `research/articles/<YYYY-MM>/<id>.json`.

**Phase 4 registry** (branch `phase-4-items`), commits `a93e881` (docs), `c53b66e` (Step 1 registry core) and `3891ef4` (Step 2a):
- Package `registry/`: db, ids, statuses, items, versions, decisions, audit, redact; stubs for jobs, auth, migrate.
- SQLite `state/registry.db`. BG IDs, five statuses, versions, revise/resubmit, append-only events, redaction.
- 240 tests pass.
- Read `docs/phases/PHASE-4-PRD.md` §1–§14. §14 holds the binding decisions D-1…D-21.

### 1.5 Existing skills and phrases
- **show-content:** "show content", "what's new", "new ideas from my newsletters"
- **make-calendar:** "make calendar [next week]", "approve all", "approve 1 3 5", "reject 2", "generate approved", "ok"
- **make-content:** "make 3", "make a post about X", "make an insta post / facebook ad / reel about X"
- **make-carousel:** "continue carousel <folder>"
- **make-video**
- **Playbooks:** "sync drive", "show tracker", "export tracker", "train lora"

"ok" is the only spending approval word.

---

## 2. Hard rules (never break)
1. **Scope:** only what §5–§7 describe. Not allowed:
   - LoRA, ComfyUI, RunPod or Nano Banana changes
   - Phase 7+ work (review-gated Drive upload, YouTube/podcast production tracking, Opus Pro, publishing, monthly report)
   - removing existing features
2. **No paid calls.** No real calls to Google APIs, Higgsfield, HeyGen, OpenRouter or RunPod. Free web fetching is allowed only in runtime code paths, never in tests and never to "try it out". Tests use fakes and fixtures.
3. **Secrets:** never read, print, copy or commit `.env`, `.secrets/` or tokens. Everything written to the audit log goes through `registry/redact.py`.
4. **Git:**
   - Commit after every step on the phase branch, with the message `phase <N> step <M>: <summary>`.
   - Never push, merge, rebase, force or delete branches.
   - Never commit `.secrets/`, `.env`, `outputs/`, `calendar/`, `state/`, photos or fonts.
5. **Checks before every commit:** `uv run ruff check .`, `uv run mypy --strict` (same targets as now) and the **full** `uv run pytest`. All must pass. Don't skip or delete existing tests to make them pass. Fix, or stop (§3.3).
6. **Library boundary:** all registry/state logic lives in `registry/` (no SQL elsewhere). The CLI stays thin, and skills only call `ca`.
7. **Honesty (BR-07, BR-14):**
   - Never mark anything verified, approved, uploaded or published without the event that proves it.
   - Mock results are always labelled mock.
8. **Backwards compatibility:**
   - Existing phrases and commands keep working (now going through the registry).
   - Old files (v1 packages, old calendar headers, old carousel.json) are still read.
9. **Skills never decide on the user's behalf.**
   - Approve, reject, revise and "ok" happen only after the user's own words.
   - A skill passes `--authorize <dryrun_id>` only after the user said "ok" to that dry run in the same conversation.

---

## 3. Working loop

### 3.1 Per phase
1. Create the branch:
   - Phase 4 continues on `phase-4-items`.
   - Phase 5: `git switch -c phase-5-research` from the last Phase 4 commit.
   - Phase 6: `git switch -c phase-6-scripts` from the last Phase 5 commit.
2. **Phase 5 and 6 only:** write `docs/phases/PHASE-<N>-PRD.md` from the spec in §6/§7. Copy its sections and wording, and add nothing outside scope.
3. Run a short code audit (use a subagent) and append "## Conflicts with the current code". For each conflict, record the option you chose using §3.2.
4. Add the phase checklist to `docs/PROGRESS.md`, then commit `phase <N> step 0: PRD`.
5. Do the build steps in order (§3.1 per step below).
6. The last step of each phase:
   - updates the skills and the AGENTS.md phrases
   - adds the phrases to `ca help commands`
   - runs the phase's offline end-to-end script
   - writes `docs/phases/PHASE-<N>-E2E.md`, containing the PASS/FAIL per acceptance criterion and a **manual Codex Desktop test script** (phrases for the user to type, in order, with the expected result)

**Per step:**
1. Implement.
2. Write tests.
3. Run the checks (§2.5).
4. Update PROGRESS.md.
5. Append to LOG.md.
6. Commit.

### 3.2 Decision policy (when the spec doesn't say)
Choose the option that is, in this order:
1. inside scope
2. reversible
3. configurable (put the value in `config/*.json`, not in code)
4. consistent with existing code and PRD §14
5. honest and visible to the user

Record each decision:
- in the PRD under "## Decisions taken during build" (ID, decision, why)
- in LOG.md under "Needs review"

Client-dependent values get a config default plus a `"_note": "client to confirm"` entry, and are listed in the final report.

### 3.3 Stop conditions (stop, write the reason in LOG.md, and reply to the user)
- A step would need a paid or real external call, a secret, or a manual action by the user.
- Checks still fail after 3 honest fix attempts.
- A change would break an existing user-facing phrase or command with no compatible path.
- A destructive operation on user data would be needed (deleting `outputs/` or `calendar/` files, or rewriting history).
- The spec contradicts itself in a way §3.2 can't settle without changing scope.

### 3.4 LOG.md entry format
```
## <date time> — Phase <N> Step <M>: <title> — DONE | STOPPED
Commit: <hash>   Tests: <passed>/<total>
Built: <3–6 short lines>
Decisions: <IDs or "none">
Needs review: <items or "none">
```

### 3.5 Reporting to the user
Only at a stop condition, or after Phase 6 is finished:
- Write `docs/autorun/REPORT-PHASES-4-6.md` covering:
  - per phase: what's built, commits, test totals
  - all decisions taken during build
  - "Needs review" items
  - client questions
  - the manual Codex Desktop test scripts
- Reply with at most 15 lines that point to the report.

---

## 4. Codex skill conventions
- Keep the existing SKILL.md format. Each skill contains:
  - a phrase → `ca` command map
  - step-by-step instructions
  - the exact output to show the user
  - rules
- Every skill rule list includes:
  - never approve, reject, revise or say "ok" for the user
  - show BG IDs and what changed
  - show `ca` errors as they are
  - never edit state files directly
- For plugin skills (make-carousel, make-video):
  - run `ca jobs check <job_id>` before **every** plugin call: `go` → call; `skip` → reuse the recorded result; `stop` → stop and report
  - record every result with `ca`
- Commands that a skill parses support `--json`.
- Every new phrase goes into the AGENTS.md Skills map and into `ca help commands`.

---

## 5. PHASE 4 (rest): content-item foundation
Branch `phase-4-items`. PRD: `docs/phases/PHASE-4-PRD.md` (§14 is binding).

**Step 2.0 (first, small):** append the following to PRD §14, then do the AGENTS.md/CLAUDE.md cleanup and commit `phase 4 step 2.0: D-22/D-23`.
- **D-22.** An idea-gate revise is allowed when idea ∈ {proposed, approved} and generation ∈ {not_started, failed, partial}.
  - approved → revision_requested. The item can't generate until it is approved again.
  - A second revise while the item is revision_requested is refused, with a hint to use `resubmit`.
  - Starting a new version requires an approved idea (keep).
- **D-23.** AGENTS.md working rules:
  - replace "No new tests" with "ruff + mypy --strict + offline pytest must pass before every commit"
  - the commit format becomes `phase <N> step <M>: …`
  - CLAUDE.md: the Nano Banana note now says "decision in Phase 10 (roadmap v3)"

### Step 2: item commands + manage-items skill
1. New Typer sub-app `ca item`. It stays thin; the logic lives in `registry/`.
   - `list [--status <dim>=<value>] [--kind] [--week] [--json]`: BG ID, kind, title (truncated), idea/generation/review/upload status, current/approved version.
   - `status <ID> [--json]`: the five statuses, versions with feedback, last 3 decisions, a job/cost summary, package path, Drive/tracker state read from existing files, mismatches (D-7), and "Next allowed actions".
   - `approve <ID...> [--gate idea|review]`: gate inference (D5). Prints `BG-007 idea: proposed → approved (v2)` per ID. With several IDs, one failure doesn't block the others, and the failure is reported.
   - `reject <ID> "<reason>"`: the reason is required.
   - `revise <ID> "<feedback>" [--title]`: D-19/D-22.
   - `resubmit <ID> --title`
   - `history <ID>`
   - Accepts a BG ID or alias. A row number only together with `--week` (D-12).
2. `ca audit show [--since] [--type] [--item] [--limit 50] [--json]`.
3. Errors: one clear line, a non-zero exit code, no tracebacks.
4. Every command logs `command_run` (actor=user) plus `decision` events.
5. New skill `.agents/skills/manage-items/SKILL.md`:
   - phrases "show items", "what's pending", "status BG-x", "approve BG-x [BG-y]", "reject BG-x <reason>", "revise BG-x <feedback>", "resubmit BG-x", "history of BG-x", "show audit log"
   - for an idea-gate revise, the skill rewrites the topic from the feedback, shows it, and passes `--title`
   - if reject or revise has no text, ask for it
6. AGENTS.md: add the phrases, plus the line "Every item has a BG ID; accept a BG ID, Content ID or row number (row numbers need the week)."
7. Tests (CliRunner, temp DB):
   - each command
   - gate inference both ways, and the case where no gate is open
   - missing reason
   - multi-ID with one failure
   - alias lookup
   - revise with and without `--title`
   - D-22 cases

### Step 3: dry runs, authorizations, jobs, idempotency + wiring
1. **Dry runs (D-4):**
   - Each dry run is saved as `state/dryruns/<DR-YYYYMMDD-HHMMSS-xxxx>.json` with:
     - created_at, command, scope item IDs
     - lines: item, job type, provider, unit, estimate, max with retries
     - totals per provider/unit
     - expires_at (config, default 24 h)
     - used flag
   - The dry-run output prints the `dryrun_id`.
   - `--authorize <id>` refuses an unknown, expired or already-used dry run, and refuses one whose scope has changed. In each case it tells the user to run a new dry run.
2. **Authorizations (`registry/auth.py`):**
   - One row per provider/unit, grouped by dryrun_id.
   - Holds max, spent and status open/closed/exceeded.
   - `ca auth list [--open] [--json]`.
   - Jobs with a free provider (mock, local FFmpeg, Drive, Sheets) need no authorization.
3. **Jobs (`registry/jobs.py`):**
   - `open_job` (D-6 key incl. `redo_n`): an existing succeeded job → returned as reused, plus a `job_reused` event.
   - `start` checks spent + estimate ≤ max. Otherwise it raises BudgetExceeded and logs `authorization_exceeded`, and the job does not start.
   - Also: `succeed(actual, result_path)`, `fail(error)`, `cancel`.
   - A job is stale when it's running past its per-type timeout (`config/jobs.json`).
   - **Item status from jobs:**
     - the first job starting → generation queued → running
     - all generation jobs succeeded → generated
     - failures after max attempts → partial or failed
     - upload status is derived per D-16
4. **CLI:**
   - `ca jobs list [--unfinished|--failed|--item] [--json]`
   - `ca jobs check <job_id>` prints `go|skip|stop` on line 1 and the reason on line 2 (`--json` also available)
   - `ca jobs resume [ID]` resumes registered job types. Only carousel is registered (it calls the existing continue logic); every other type prints "not resumable yet".
5. **Wiring** (follow audit item d in PRD §13):
   - calendar generate, content build and `ca image` use dry run → `--authorize`
   - `run_image_job` wraps `generate_image` in a job
   - carousel: writing a still/clip request opens a job (provider higgsfield, unit credits); `ca carousel record` closes it with the credits actually used. The carousel max is taken from the authorization. Old carousel.json files still resume.
   - video_job: open/close through `ca job complete|fail`
   - Drive: one job per file, upload; and one for the tracker write
6. **Skills** (same step):
   - make-calendar and make-content: the dry run shows the dryrun_id; after "ok", run the build with `--authorize`.
   - make-carousel and make-video: `ca jobs check` before every plugin call.
7. **Tests:**
   - reuse and `redo_n`
   - budget stop
   - expired, used and changed-scope dry runs
   - stale jobs
   - generation/upload derivation
   - a carousel interrupted and then resumed (mock)
   - no job runs without an authorization when the provider is paid

### Step 4: calendar as a view + migration
1. **New CSV header:** Row, BG ID, Planned date, Topic, Research source, Platform, Content type, Status, Version, Package, Content ID.
   - The old 9-column header is still read (D-8).
   - Status is derived:
     - idea proposed → Proposed
     - revision_requested → Revision requested
     - rejected → Rejected
     - approved, generation not_started → Approved
     - queued/running → In progress
     - generated → Generated
     - failed/partial → Failed
2. **Hand-edit guard (D10):**
   - The hash of each CSV is stored in the registry on every write.
   - If the file changed since the last write: stop, print a unified diff, exit non-zero, and offer two options:
     - `ca calendar sync <week> --discard-edits`
     - `--import-edits`, which imports only Topic and Planned date, as logged updates. Status edits are never imported; the user approves or rejects instead.
3. Row numbers apply within a week only (D-12). `--replace` behaves as in D-11.
4. **`ca registry migrate [--dry-run]`:**
   - Sources: calendar CSVs, packages (v1 and v2 formats), carousel.json, drive_state.json (read-only; never print its content), and mock tracker rows.
   - Back up first. Create items oldest first, with aliases, the status mapping from PRD §9 and D-1/D-2 kinds, and v1. Log `migration_run`.
   - Rewrite old CSVs to the new header after the backup.
   - Idempotent.
   - Report: created, skipped (already migrated), unreadable (with reason).
5. Fixtures in `tests/fixtures/migration/` cover every source type (D-18). Run `--dry-run` on the 4 real local packages and paste only the counts into LOG.md.

### Step 5: tracker (mock)
1. Workflow columns (D-14): BG ID, Version, Idea status, Generation status, Review status, Upload status, Last updated. Mark the names "client to confirm" in config.
2. Match rows by BG ID, then Content ID, and fill in the BG ID (D-13).
3. Store the last-written value per cell in the registry (D-15).
4. **Upsert:**
   - Manager columns are never written.
   - A workflow cell that differs from its last-written value is a conflict. The row is skipped, and `conflict_found` is logged.
5. Commands:
   - `ca tracking conflicts [--json]`: lists hand edits, rows missing on either side, and duplicate IDs.
   - `ca tracking resolve <ID> --keep-sheet|--use-registry`
6. Update the Drive adapter code, but test it only with a fake Sheets client. Mock uploads show as "uploaded (mock)" (D-16).

### Step 6: finish Phase 4
1. `ca help commands`: phrase → effect, grouped by skill. A test checks that every phrase in AGENTS.md appears in it.
2. Update show-content and any remaining skills so they show BG IDs.
3. `scripts/e2e_phase4.py`:
   - offline, temp state dir, mock providers
   - runs acceptance criteria 1–9 of PRD §10 and prints PASS/FAIL per criterion
   - plus a pytest wrapper
4. Write `docs/phases/PHASE-4-E2E.md` with the results and the manual Codex test script (for example: "make calendar next week" → "approve BG-001 BG-002" → "reject BG-003 too generic" → "revise BG-004 …" → "status BG-004" → "generate approved" → "ok" → "show audit log").
5. Update README/PROGRESS. Commit.

---

## 6. PHASE 5: strategy, research and idea backlog
Branch `phase-5-research`. Write this as `docs/phases/PHASE-5-PRD.md` (Step 0).

### 6.1 Goal
All ideas, whether from newsletters, articles, web research or the user's own topics, go into **one backlog**:
- each idea has a BG ID
- each idea is linked to its sources and labelled claims
- duplicates are merged, and ideas are scored against the new strategy
- ideas wait in a review queue

Approved ideas feed **calendar v2**, which covers all platforms and the monthly targets.

### 6.2 Spec coverage
UC-02 (newsletters), UC-03 (research with source verification), UC-04 (manual topics), UC-05 (consolidation/dedupe), UC-06 (calendar), BR-02, BR-03, BR-07, BR-10.

### 6.3 Out of scope
- scripts and briefs (Phase 6)
- generation changes
- YouTube/podcast production (the calendar only plans them)
- real Gmail or web calls in tests
- enabling German sources without client confirmation

### 6.4 Decisions
- **P5-D1 Ideas are items.**
  - New kind `idea`. An idea uses only the idea gate; generation, review and upload are n/a and shown as "—".
  - Content items planned from an idea get `parent_id` = the idea, which gives the chain idea → youtube → short (BR-03).
  - Approving, rejecting and revising ideas reuse `ca item …` and the manage-items phrases.
- **P5-D2 Strategy config `config/strategy.json`:**
  - pillars `german_problems`, `ai_risks`, `ai_misuse`, `ai_mistakes`, `ai_solutions`, each with a description, keywords (DE + EN) and a target share
  - audiences and exclusions
  - The values are a draft with `"_note": "client to confirm"`.
- **P5-D3 Content language:**
  - `config/content.json` → `language` (default **"en"**, the current behaviour) plus per-platform overrides
  - marked "client to confirm (DE vs EN)"
  - No silent switch to German.
- **P5-D4 Sources table (registry migration):**
  - fields: id `SRC-####`, type newsletter|article|web|manual, url, original_url, title, publisher, language, published_at, fetched_at, purpose, trust primary|secondary|unknown, text_path
  - links idea ↔ source
- **P5-D5 Claims table:**
  - id `CL-####`, idea, text, label fact|opinion|speculation, status verified|unverified|disputed|outdated, source refs, checked_at
  - The **Codex skill proposes** the label and text from the source text. **`ca` enforces the rules mechanically:**
    - a fact needs at least one source with a URL and published_at
    - it is `verified` only with 2 independent publishers or 1 `primary` source; otherwise `unverified`
    - an opinion needs an attributed source
    - `disputed` needs the refs of both sides
    - `outdated` if published_at is older than `research.max_age_days` (config, default 90)
  - Codex can never set `verified` directly.
- **P5-D6 Newsletters:**
  - `config/newsletters.json` gets a `senders` list: domain, name, purpose, pillar affinity, follow_links, `"verified_domain": false`.
  - Unknown senders are reported, not dropped.
- **P5-D7 Link following:**
  - `ca research fetch <url> [--idea BG-x]` follows redirects and tracking links to the original article.
  - It stores the text plus metadata as a source and records both the newsletter URL and the original URL.
  - It is a free HTTP fetch in runtime only (tests use fixtures), with timeout, size limit and robots.txt respected. Failures are reported per URL.
- **P5-D8 German sources:**
  - `config/sources.json` v2 fields: language, region, type rss|html, pillar hints, trust, `enabled`.
  - Add candidates with `"enabled": false, "_note": "candidate — client to confirm; feed URL unverified"`: tagesschau.de, heise online, netzpolitik.org, golem.de, t3n, BSI (press), Destatis (press), BfDI.
  - The existing US sources stay enabled.
- **P5-D9 Dedupe:**
  - `ca` normalizes titles and compares them (stdlib difflib + token overlap, threshold in config).
  - A URL match is always a duplicate. Duplicates are merged into the older idea, sources are added to it, and `duplicate_of` is recorded and logged.
- **P5-D10 Scoring (0–100), weights in config:**
  - pillar relevance 0–40 (Codex gives 1–5 + a one-line reason)
  - German relevance 0–20 (Codex: yes/partial/no)
  - recency 0–15 (computed)
  - source trust 0–15 (computed)
  - evidence 0–10 (number of verified facts)
  - No pillar → flag `off_strategy`. It is shown, never auto-rejected. Codex-provided parts are stored with actor=assistant.
- **P5-D11 Manual topics:**
  - `ca ideas add "<text>" [--notes] [--platform]` keeps the original input verbatim and records the assumptions Codex makes.
  - It goes through the same dedupe and scoring path.
- **P5-D12 Calendar v2:**
  - `config/calendar.json` v2 has slots per platform/kind to meet the monthly targets: posts/graphics 1–2 per day across LinkedIn, Facebook and Instagram; 1 carousel/week; 2 YouTube/week; podcasts on a configured schedule; Shorts derived from YouTube.
  - TikTok and Shorts slots are created only from a parent video.
  - `ca calendar plan --week|--month` fills slots from **approved ideas** by score and pillar balance.
  - Rows created from an approved idea start with idea=approved (inherited, logged with the parent ID). Manual or legacy rows start as Proposed.
  - Dependencies: a short's planned date must be ≥ its parent's date + buffer (config); otherwise the row shows "blocked: waiting for BG-x".
  - `ca calendar show --month`.
  - `generate approved` skips kinds that have no pipeline yet (youtube, podcast, short) and says "not producible until Phase 8/9".
  - The old weekly flow ("make calendar next week") keeps working.
- **P5-D13 Run counts:** each research run reports collected / duplicates / off_strategy / flagged claims / failed fetches (UC-02).

### 6.5 Commands
| Command | Codex phrase |
|---|---|
| `ca ideas list [--status] [--pillar] [--min-score] [--json]` | "show backlog", "show ideas" |
| `ca ideas review [--limit 10]` (queue, best first, with sources and flags) | "review ideas" |
| `ca ideas add "<text>"` | "add topic …" |
| `ca ideas score BG-x --pillar --relevance --german --reason` | (used by the skill) |
| `ca ideas merge BG-x BG-y` | "merge BG-x into BG-y" |
| `ca research fetch <url> [--idea]` | "research this link …" |
| `ca research run [--sources] [--newsletters]` | "find new ideas" |
| `ca claims add/list/check BG-x` | "show claims for BG-x" |
| `ca calendar plan --week\|--month` | "plan next week", "plan next month" |
| `ca calendar show --month` | "show month" |

Approve, reject and revise of ideas use the existing `ca item` commands and phrases.

### 6.6 Skills
- **New `research-ideas` skill:**
  - Gmail fetch (existing account and label rules).
  - Follow links with `ca research fetch`.
  - Propose claims, labels and scores from the fetched text only.
  - Never invent sources or URLs.
  - If the text is missing, say so.
- **Update `show-content`** to use it.
- **Update `make-calendar`** with the plan phrases.

### 6.7 Acceptance criteria (offline)
1. Newsletter fixtures produce ideas with sources, purposes, the original URLs and run counts.
2. A duplicate idea from another source is merged, and the sources are kept.
3. A fact with one secondary source is `unverified`. Two publishers make it `verified`. An old date makes it `outdated`. Codex cannot set `verified` directly.
4. A manual topic keeps its original text and goes through dedupe and scoring.
5. An off-strategy idea is flagged, not dropped.
6. `calendar plan --month` meets the configured targets from approved ideas, keeps the pillar balance within config tolerance, and blocks shorts until their parent is planned.
7. Approving an idea and planning it creates child items with parent_id and inherited approval in the log.
8. `generate approved` skips youtube/podcast/short with a clear message.
9. German candidate sources are present but disabled.
10. All checks pass.

### 6.8 Build steps
0. PRD + conflicts.
1. Registry migration: kind `idea`, sources, claims, idea↔source links, `duplicate_of`; strategy and content configs.
2. Newsletter senders config, `ca research fetch` with link resolution, source storage (fixtures).
3. Sources config v2 + scraper update + German candidates (disabled) + `ca research run`.
4. Dedupe, scoring, the review queue, manual topics, claim rules and commands.
5. Calendar v2 (slots, targets, inherited approval, dependencies, month view, skip unbuilt kinds).
6. Skills (research-ideas; show-content and make-calendar updates), AGENTS.md, help, `scripts/e2e_phase5.py`, PHASE-5-E2E.md (with the Codex test script), PROGRESS.

---

## 7. PHASE 6: editorial formulas, scripts and production briefs
Branch `phase-6-scripts`. Write this as `docs/phases/PHASE-6-PRD.md` (Step 0).

### 7.1 Goal
Every content item can get formula-based copy or a script plus a production brief:
- written by Codex
- built only from the item's research claims
- validated and versioned by `ca`

### 7.2 Spec coverage
UC-08 (scripts and production briefs), editorial formulas, BR-03, BR-06, BR-07, BR-09.

### 7.3 Out of scope
- recording, editing and production statuses (Phase 8)
- the review command and review-gated upload (Phase 7)
- image/video generation changes
- Shorts/Opus clip scripts (Phase 9)
- translation beyond `config/content.json`

### 7.4 Decisions
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

### 7.5 Commands
| Command | Codex phrase |
|---|---|
| `ca script template BG-x [--json]` (skeleton, claims with status, feedback, platform rules, language) | (used by the skill) |
| `ca script save BG-x <file>` (validate, store, render md) | (used by the skill) |
| `ca script check BG-x` | "check script BG-x" |
| `ca script show BG-x [--version]` | "show script BG-x" |
| `ca brief template/save/check/show BG-x` | "write brief for BG-x", "show brief BG-x" |

### 7.6 Skills
**New `write-script` skill:**
- Phrases: "write script for BG-x", "write copy for BG-x", "write brief for BG-x", "rewrite script BG-x <feedback>" (revise first), "show script BG-x".
- Rules:
  - use only the claims from the template
  - never invent facts, numbers, quotes or sources
  - if research is thin, say so and suggest "research this link …" / "find new ideas"
  - show a short summary plus the check result, and the full text only on request

**Update `make-content`** so post, carousel and ad copy goes through the template/save path.

### 7.7 Acceptance criteria (offline)
1. Templates exist for every formula and include the claims and the feedback.
2. A valid YouTube script fixture saves as v1 with md rendered and a duration estimate.
3. A missing section, a number without a verified source, an outdated claim, or an unacknowledged unverified claim each fail with a clear message.
4. A revise then a new save creates v2, and v1 is unchanged.
5. Podcast and YouTube briefs validate and render.
6. LinkedIn copy outside 120–250 words fails.
7. Existing post and carousel builds still work on mock, and old packages still render.
8. All checks pass.

### 7.8 Build steps
0. PRD + conflicts.
1. `config/formulas.json`, JSON schemas, the artifacts table, `ca script template`.
2. Validation rules, `save/check/show`, the md renderer.
3. YouTube and podcast briefs (`ca brief …`).
4. Move post, carousel and ad copy onto the formulas (keeping compatibility).
5. The write-script skill, make-content update, AGENTS.md, help, `scripts/e2e_phase6.py`, PHASE-6-E2E.md (with the Codex test script), PROGRESS.

---

## 8. Finish
After Phase 6 Step 5:
- write `docs/autorun/REPORT-PHASES-4-6.md` (§3.5)
- make the final LOG.md entry
- stop

Do **not** start Phase 7.
