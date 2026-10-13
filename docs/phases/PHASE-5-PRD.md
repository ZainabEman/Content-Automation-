# Phase 5 PRD — Strategy, research and idea backlog (v3 spec)
Branch: phase-5-research (from phase-4-items, 29c8926). Date: 13 Oct 2026. Source: docs/autorun/AUTORUN-PHASES-4-6.md §6.

## 1. Goal
All ideas, whether from newsletters, articles, web research or the user's own topics, go into **one backlog**:
- each idea has a BG ID
- each idea is linked to its sources and labelled claims
- duplicates are merged, and ideas are scored against the new strategy
- ideas wait in a review queue

Approved ideas feed **calendar v2**, which covers all platforms and the monthly targets.

## 2. Spec coverage
UC-02 (newsletters), UC-03 (research with source verification), UC-04 (manual topics), UC-05 (consolidation/dedupe), UC-06 (calendar), BR-02, BR-03, BR-07, BR-10.

## 3. Out of scope
- scripts and briefs (Phase 6)
- generation changes
- YouTube/podcast production (the calendar only plans them)
- real Gmail or web calls in tests
- enabling German sources without client confirmation

## 4. Decisions
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

## 5. Commands
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
| `ca calendar plan --week\\|--month` | "plan next week", "plan next month" |
| `ca calendar show --month` | "show month" |

Approve, reject and revise of ideas use the existing `ca item` commands and phrases.

## 6. Skills
- **New `research-ideas` skill:**
  - Gmail fetch (existing account and label rules).
  - Follow links with `ca research fetch`.
  - Propose claims, labels and scores from the fetched text only.
  - Never invent sources or URLs.
  - If the text is missing, say so.
- **Update `show-content`** to use it.
- **Update `make-calendar`** with the plan phrases.

## 7. Acceptance criteria (offline)
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

## 8. Build steps
0. PRD + conflicts.
1. Registry migration: kind `idea`, sources, claims, idea↔source links, `duplicate_of`; strategy and content configs.
2. Newsletter senders config, `ca research fetch` with link resolution, source storage (fixtures).
3. Sources config v2 + scraper update + German candidates (disabled) + `ca research run`.
4. Dedupe, scoring, the review queue, manual topics, claim rules and commands.
5. Calendar v2 (slots, targets, inherited approval, dependencies, month view, skip unbuilt kinds).
6. Skills (research-ideas; show-content and make-calendar updates), AGENTS.md, help, `scripts/e2e_phase5.py`, PHASE-5-E2E.md (with the Codex test script), PROGRESS.

## Conflicts with the current code
Short audit on 13 Oct 2026 (branch phase-5-research at 29c8926). Each conflict: what the code does today → the option chosen (§3.2: in scope, reversible, configurable, consistent with Phase 4, honest).

- C5-1 `research/models.py` `Source`/`SourcesFile` forbid extra fields, so sources.json v2 fields would stop `ca research collect` and `ca doctor`. → Add the v2 fields to the model as optional (language, region, type, pillarHints, trust, enabled, _note), defaults that keep today's behaviour.
- C5-2 sources.json already has `active`; the plan names `enabled`. → `enabled` is the v2 field; `active` stays accepted for old entries. A source runs only if neither is false.
- C5-3 RSS vs homepage is decided today by `rssUrl` being set; the plan adds `type rss|html`. → `type` is optional; without it the old rule applies; `type: rss` requires an rssUrl.
- C5-4 `content/calendar.py` `Cadence`/`Slot` forbid extra fields. → calendar.json keeps its weekly `slots` (the old "make calendar next week" flow, unchanged) and gains an optional v2 `plan` block (targets, slots per platform/kind, schedules, dependencies), loaded by a new model.
- C5-5 Platforms are only instagram, facebook and linkedin (`content/brief.py`, tracker, Drive folders); there is no youtube, podcast or graphic deliverable, and `Deliverable` cannot hold one. → Brief and deliverable platforms stay as they are (generation is out of scope). Calendar v2 adds plan-only content types in calendar.json (e.g. youtube_longform, podcast_episode, youtube_short, tiktok_short) with their platform and kind; `check_calendar` accepts them and `generate approved` skips them ("not producible until Phase 8/9").
- C5-6 `generate_rows` runs `check_calendar` first, so one unknown row stops the week. → Fixed by C5-5: plan-only rows pass the check and are skipped by generate with the message.
- C5-7 Registry `KINDS` has no `idea`. → Add `idea` (kinds are checked in code; no SQL change).
- C5-8 Item list, status, report and `next_actions` assume generation, review and upload (an approved idea would be offered "generate"). → For kind idea these show "—" and the next actions are approve/reject/revise or "plan it" (`ca calendar plan`).
- C5-9 `parent_id` exists but is never set or shown. → Calendar v2 sets it on items planned from an idea (and on shorts from their video); status, list JSON and history show it.
- C5-10 `parse_id` knows only BG IDs. → SRC-#### and CL-#### get their own counters in `id_counter` and their own parse/format functions.
- C5-11 A calendar Research source must be topic:/newsletter:/article:. → Also accept `idea:BG-x` (rows planned from an approved idea) and check it against the registry.
- C5-12 Calendars are weekly CSV files. → `calendar plan --month` writes the month's rows into each week's CSV (row numbers stay per week, D-12); `calendar show --month` combines the weeks.
- C5-13 A calendar row has one platform. → Cross-platform targets become one row per platform.
- C5-14 There is no graphic deliverable and Instagram has only the carousel. → The posts/graphics target counts the producible post deliverables (LinkedIn, Facebook) per day; Instagram gets its weekly carousel; an Instagram single-graphic slot is a plan-only type, off by default in config (client to confirm).
- C5-15 newsletters.json is read only by the skill. → Add `senders`; Python reads it in `ca research run --newsletters` (purpose, pillar affinity, follow_links; unknown senders reported).
- C5-16 The scraper's fetch helpers are private, check robots.txt only for the first URL, and have no size limit. → A new `research/fetch.py` for `ca research fetch`: redirects followed with a cap, robots.txt checked for the first and the final URL, timeout and size limit from config, trafilatura extraction; tests use httpx's MockTransport.
- C5-17 "English only" is written into the brief template, AGENTS.md and the skills. → config/content.json `language: "en"` (client to confirm DE vs EN) is added and read where Phase 5 writes text (ideas, claims); the existing English rules stay (same behaviour; no silent switch). Phase 6 uses it for scripts.
- C5-18 brand.json `contentPillars` (marketing topics) differ from the strategy pillars. → config/strategy.json is the source for idea scoring; brand.json stays for the existing briefs (no silent change).
- C5-19 Articles keep their text inline in research/articles JSON; sources need a text_path. → Sources from articles point at the article JSON; fetched pages are saved as research/sources/SRC-####.txt (git-ignored with research/).
- C5-20 Newsletter list sources may have no URL (`email:<hash>` articles). → A newsletter source may have no URL; it is then never "verified" as a fact source (needs a URL, P5-D5).
- C5-21 The make-calendar skill and AGENTS.md describe the 5-slot weekly cadence; `ca help commands` maps the old phrases. → Kept for "make calendar next week"; the plan phrases are added in Step 5/6 (help test keeps AGENTS.md and help in step).
