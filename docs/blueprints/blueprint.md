# Codex-Based AI Automation System — Technical Decision & Implementation Blueprint

> Markdown copy of `AI_Automation_Technical_Implementation_Blueprint.docx` (source of truth).
> Developer-facing specification for the complete three-branch automation platform. Prepared for development use — September 2026.

**Implementation principle:** Codex orchestrates. Specialized services execute. APIs are the default deterministic integration layer. MCP is used only where it materially improves agent/tool control.

| Branch | Purpose | Build order |
| --- | --- | --- |
| 1. AI Image Generation | Reference-based brand imagery and social creatives | FIRST |
| 2. AI Content & Video | UGC, Reels/Shorts, Podcast/video workflows | SECOND |
| 3. Article Scraping & AI Research | Collect sources, analyze trends, generate content opportunities | THIRD |

---

## 1. Executive Summary

The business brief describes three connected AI automations with Codex as the central controller. This document converts that brief into an implementation-oriented architecture with explicit responsibilities, integration boundaries, data contracts, phases, testing gates, and open decisions.

The implementation will be incremental. Branch 1 (image generation) is the first development target. Branch 2 (video/content) and Branch 3 (research/scraping) are designed now at the interface level but are not implemented until the image branch reaches its MVP acceptance criteria.

Current known resources: paid Codex/ChatGPT desktop access, paid Higgsfield, paid HeyGen, and paid ElevenLabs. API access, quotas, and credits must still be verified for the specific accounts before production integration.

For the image branch, the current decision is to use reference/few-shot identity conditioning rather than training a LoRA. The 7–8 images of the person are identity references. Facebook, Instagram, and carousel examples are creative/brand references and must not be treated as identity-training images.

**Key architectural rule:** Codex owns orchestration and workflow selection. Specialized providers own execution. ComfyUI, if selected, is the image workflow engine—not the business-logic controller.

## 2. Requirements Converted into Technical Scope

| Business requirement | Technical interpretation | Status |
| --- | --- | --- |
| Codex is the central AI controller | Agent/orchestrator selects workflows, prepares inputs, invokes tools, receives outputs | Core architecture |
| Image generation | Reusable image workflow engine + model/reference conditioning; LoRA replaced by reference approach for MVP | Branch 1 |
| UGC / Reels / Podcast | Provider adapters and reusable video/audio workflows | Branch 2 — later |
| Article research | Source collection → normalization → storage → Codex analysis | Branch 3 — later |
| Branches work together | Stable handoff contracts between research, content, image, video and audio workflows | Architecture now |

## 3. Target System Architecture

```
USER / FUTURE UI
        |
        v
+---------------------------+
| CODEX ORCHESTRATOR        |
| - understand request      |
| - choose workflow         |
| - validate inputs         |
| - call tools              |
| - track job state         |
+-------------+-------------+
              |
       TOOL / API LAYER
              |
   +----------+----------+----------------+
   |                     |                |
   v                     v                v
IMAGE BRANCH         VIDEO BRANCH      RESEARCH BRANCH
   |                     |                |
ComfyUI / selected      Higgsfield       own free
image provider          HeyGen           scraper (RSS + pages)
   |                     |                |
FLUX / reference        ElevenLabs       sources
conditioning            audio            |
   |                     |                |
   +----------+----------+----------------+
              |
              v
      ASSET + METADATA STORAGE
              |
              v
        OUTPUT PACKAGE
```

Codex should be the orchestration layer. Provider-specific operations should be hidden behind adapters so the rest of the system is not coupled to one vendor's request format.

### Integration rules

- Prefer official APIs for deterministic provider operations.
- Use MCP when it makes a tool naturally callable by Codex and exposes the controls actually required.
- Do not add MCP merely because MCP exists.
- Never expose provider secrets to prompts or client-side code.
- Keep provider-specific request/response formats inside provider adapters.

## 4. Technology Decision Register

| Component | Current decision | Reason / notes | Status |
| --- | --- | --- | --- |
| Orchestration | Codex Desktop | Central agent and development control plane | Selected |
| Image workflow | ComfyUI candidate | Reusable node workflows and API/server model; verify deployment route | Validate |
| Image model | FLUX candidate | Requested direction; exact variant and reference mechanism must be verified | Validate |
| Person identity | Reference/few-shot conditioning | 7–8 reference images; no LoRA for MVP | Selected |
| Video | Higgsfield | Paid account; later branch | Selected |
| Avatar | HeyGen | Paid account; later branch | Selected |
| Voice | ElevenLabs | Paid account; later branch | Selected |
| Scraper | Own free scraper (httpx, feedparser, trafilatura) | RSS first, else homepage links; polite, no account | Selected |
| Scraper alternative | Firecrawl | Useful if clean AI-ready crawling/extraction is the priority | Alternative |
| Asset storage | Object storage — TBD | Persistent generated files and URLs | Open |
| Metadata DB | Postgres-class DB — TBD | Jobs, assets, sources, workflows and metadata | Open |
| Job execution | Provider async job adapter | Long-running generation needs IDs, status, retry and timeout handling | Required |

## 5. Branch 1 — AI Image Generation

This is the first branch to implement. The original business brief describes an image workflow centered on Codex, ComfyUI, a generation model, and output storage. For this implementation, the LoRA portion is intentionally replaced by reference/few-shot identity conditioning.

### 5.1 MVP objective

The MVP is complete when Codex can accept a natural-language request plus the person's reference images, invoke the selected image workflow, generate a new image containing the same person, save the result, and record generation metadata.

### 5.2 Identity reference assets

- Reference set: approximately 7–8 images of the target person.
- These images are identity references, not generic style examples.
- Inspect the images for resolution, face visibility, pose variation, lighting variation, and identity clarity.
- If the reference set is weak, improve the references before trying to solve the problem with more prompting.
- Do not train a LoRA for the MVP.
- Use the exact reference-image mechanism supported by the selected FLUX/image system; do not invent an unsupported 'few-shot' parameter.

### 5.3 Brand and creative references

- Facebook sample posts.
- Instagram sample posts.
- Carousel examples.
- Brand logo, colors, typography, and other guidelines when available.
- Product photos from useful angles when product accuracy matters.

Identity references control who the person is. Brand/creative references control how the visual should look. Keep these input categories separate in code, storage, and metadata.

## 6. Image Workflow Architecture

```
Natural-language request
        |
        v
Codex: classify creative request
        |
        +--> choose image workflow
        +--> choose model/provider
        +--> select reference set
        +--> build generation parameters
        |
        v
Image Adapter
        |
        v
ComfyUI / selected image API
        |
        +--> base image model
        +--> identity/reference conditioning
        +--> optional product reference
        +--> prompt/style controls
        |
        v
Generated asset
        |
        +--> validate output
        +--> save file
        +--> save metadata
        |
        v
Codex result
```

### 6.1 Initial tool contract

```
generate_person_image(
    prompt,
    reference_images,
    aspect_ratio,
    output_format,
    optional_brand_reference,
    optional_product_reference
) -> GenerationResult
```

### 6.2 Future workflow registry

| Workflow ID | Purpose | MVP? |
| --- | --- | --- |
| person_lifestyle | Person in a requested environment or scene | YES |
| person_product | Person interacting with a product | After identity MVP |
| product_hero | Product-only hero creative | Later |
| social_creative | Image designed for a social post/ad | Later |
| facebook_ad | Facebook-oriented static ad composition | Later |
| instagram_creative | Instagram-oriented creative | Later |
| carousel_slide | Reusable carousel image/slide | Later |
| thumbnail | Thumbnail/supporting visual | Later |

## 7. FLUX + ComfyUI Integration Decision

ComfyUI is a candidate execution layer because it supports node-based workflows and can expose workflows through an API/server. The exact FLUX model, reference mechanism, custom nodes, and deployment route must be verified before implementation.

### Required verification before coding

- Which exact FLUX model or provider will be used?
- Does it support the required reference-image/identity conditioning?
- Can the selected reference mechanism be invoked through ComfyUI?
- Which nodes or custom nodes are required?
- Can the workflow be exported as a stable API workflow?
- Where will generation run: local GPU, cloud GPU, or provider API?
- What resolutions and aspect ratios are supported?

Do not commit to 'FLUX MCP' as an architecture until the actual available MCP/API capability is verified. If a direct official API is simpler and meets the identity requirement, the image adapter should support that route instead of forcing an MCP.

## 8. Core Data Contracts

### 8.1 Asset

```
Asset {
  asset_id: string
  type: "image" | "video" | "audio" | "document"
  uri: string
  mime_type: string
  provider: string
  created_at: datetime
  metadata: object
}
```

### 8.2 ImageGenerationJob

```
ImageGenerationJob {
  job_id: string
  workflow_id: string
  provider: string
  provider_job_id: string | null
  prompt: string
  reference_asset_ids: string[]
  product_asset_ids: string[]
  brand_reference_asset_ids: string[]
  parameters: object
  status: queued | processing | completed | failed | cancelled
  output_asset_ids: string[]
  error: object | null
  created_at: datetime
  updated_at: datetime
}
```

### 8.3 Workflow

```
Workflow {
  workflow_id: string
  name: string
  version: string
  provider: string
  input_schema: object
  output_schema: object
  enabled: boolean
}
```

### 8.4 Future research record

```
SourceArticle {
  article_id: string
  source: string
  url: string
  title: string
  published_at: datetime | null
  content: string
  summary: string | null
  topics: string[]
  collected_at: datetime
}
```

## 9. Output Storage & Metadata

Keep binary assets separate from structured metadata.

```
Object storage
  /assets/images/{asset_id}.png
  /assets/videos/{asset_id}.mp4
  /assets/audio/{asset_id}.mp3

Database
  assets
  generation_jobs
  workflows
  brand_assets
  reference_sets
  future: articles, content_briefs
```

For the first local MVP, project output storage is acceptable if it is practical. The storage adapter should hide the physical location so it can later be replaced by persistent object storage without changing Codex's tool contract.

Every generated asset should be traceable to the prompt, workflow version, provider, model, references, and job that produced it.

## 10. Job Lifecycle & Reliability

```
SUBMITTED
   |
   v
QUEUED
   |
   v
PROCESSING
   |    |  +--> RETRYING --> PROCESSING
   |
   +----> COMPLETED --> OUTPUT STORED
   |
   +----> FAILED
   |
   +----> CANCELLED
```

Long-running provider calls must not be treated as synchronous unless the provider explicitly guarantees synchronous completion. Store the provider job/request ID, poll or receive a webhook, apply timeout/backoff rules, and persist terminal state.

## 11. Branch 2 — AI Content & Video Production

The business brief describes UGC advertisements, Reels/Shorts, and Podcast workflows. UGC Factory is one workflow inside the larger video system.

| Service | Role |
| --- | --- |
| Higgsfield | Video generation, image-to-video, and other video workflows |
| HeyGen | Talking avatar / presenter workflows |
| ElevenLabs | Voice generation and audio layer where needed |
| Codex | Concept, hook, script, scene planning, provider selection, and orchestration |

### Future sub-workflows

- UGC ad: product → angle → hook → script → creator/video generation → final ad.
- Reel/Short: topic → research → script → scenes → video generation → final reel.
- Podcast: topic → research → script → avatar/presenter → voice/video → final content.

## 12. Branch 3 — Article Scraping & AI Research

The business requirement is to collect title, source, date, link, and main content/summary, then send the structured data to Codex for relevance, trend analysis, and content idea generation.

### Selected approach: our own free scraper

A small scraper of our own, built only on free open-source libraries (httpx, feedparser,
trafilatura): no paid scraping API and no account. It reads each source's RSS feed (or, if
there is none, the homepage's article links), respects robots.txt, waits 1–2 s between
requests, and extracts title, date, author and clean text from each article.

```
Source configuration
      |
      v
free scraper (RSS / homepage links → trafilatura)
      |
      v
raw result
      |
      v
normalizer + deduplicator
      |
      v
SourceArticle records
      |
      v
Codex research analysis
      |
      +--> trend
      +--> content idea
      +--> reel topic
      +--> carousel topic
      +--> LinkedIn topic
      +--> podcast topic
```

### Selection gate

Do not implement the scraper until the actual list of websites, blogs/news sources, and collection frequency is known. Firecrawl remains an alternative if the actual requirement is primarily clean AI-ready crawling/extraction.

## 13. Cross-Branch Orchestration

```
RESEARCH
  |
  v
Content Brief
  |
  v
CODEX
  |
  +----> Video Script ----> Higgsfield / HeyGen
  |
  +----> Image Brief ------> Image Branch
  |
  +----> Voice ------------> ElevenLabs
  |
  v
Content Package
  |
  +-- video
  +-- images
  +-- audio
  +-- script
  +-- metadata
```

The handoff should be a structured ContentBrief rather than raw prose.

```
ContentBrief {
  brief_id
  topic
  audience
  platform
  objective
  hook
  key_points[]
  script
  visual_requirements[]
  image_requirements[]
  video_requirements[]
  voice_requirements[]
  brand_constraints[]
}
```

## 14. API vs MCP Decision Framework

| Use API when... | Use MCP when... |
| --- | --- |
| The operation is deterministic and provider-specific. | The operation benefits from agent-driven tool selection. |
| Exact schemas, retries, status polling, and validation are required. | The MCP exposes the actual controls needed without hiding important parameters. |
| The provider has an official API/SDK. | The provider has a trustworthy, current MCP server. |
| A stable backend integration is needed independent of a particular agent. | Codex should call the operation naturally as an agent tool. |

Do not build an MCP server for every provider just for architectural symmetry. MCP is a tool interface; APIs remain the deterministic integration layer where appropriate.

## 15. Security & Secrets

- All API credentials are environment/secret values, never source-code constants.
- Do not put credentials inside Codex prompts or generated documentation.
- Do not commit .env files or provider keys to Git.
- Log provider request IDs and internal job IDs, not secret headers.
- Validate uploaded reference assets and control access to stored assets.
- Use least-privilege or scoped credentials where providers support them.
- Keep provider keys server-side; never expose them to browser/client code.

## 16. Master Implementation Plan

### Phase 0 — Repository & environment preparation

- Create or confirm the repository.
- Inspect the existing project structure.
- Define environment variable strategy.
- Create provider adapter boundaries.
- Create minimal asset/job data models.
- Add setup and test documentation.

**Exit gate:** project runs locally with a clean baseline.

### Phase 1 — Image integration verification

- Verify exact FLUX model/provider.
- Verify reference-image/identity capability.
- Verify whether ComfyUI is required or useful.
- Verify exact API/MCP route.
- Run one manual generation if necessary to establish expected quality.

**Exit gate:** known-good generation path and documented request/response contract.

### Phase 2 — Reference asset ingestion

- Add the 7–8 identity images.
- Create a named reference set.
- Validate image formats and resolution.
- Store metadata and stable asset IDs.
- Keep identity references separate from brand/style references.

**Exit gate:** Codex/tool layer can retrieve the correct reference set.

### Phase 3 — First automated person-image workflow

- Implement one generate_person_image tool.
- Connect Codex to the image adapter.
- Generate a new scene using the reference set.
- Save output and metadata.
- Implement clear failure handling.

**Exit gate:** end-to-end generation works without manual provider intervention.

### Phase 4 — Identity quality evaluation

- Test poses, backgrounds, lighting, clothing, camera angle, environments, and person + product.
- Record failures and adjust the reference mechanism/workflow.

**Exit gate:** identity quality is acceptable for intended brand use.

### Phase 5 — Brand/style workflow library

- Translate Facebook/Instagram/carousel examples into explicit visual rules.
- Build reusable workflows.
- Add aspect-ratio presets.
- Add product-reference handling.
- Add social/ad creative variants.

**Exit gate:** repeated creative types can be generated predictably.

### Phase 6 — Storage and production hardening

- Move assets to persistent object storage if required.
- Move metadata to a production database.
- Add retry/backoff/timeouts.
- Add structured logs and provider request IDs.
- Add test fixtures.

**Exit gate:** reliable, traceable image service.

### Phase 7 — Video branch

- Integrate Higgsfield.
- Integrate HeyGen.
- Integrate ElevenLabs.
- Implement UGC, Reels/Shorts, and Podcast workflows.

**Exit gate:** selected video/audio workflows run end-to-end.

### Phase 8 — Research branch

- Confirm target sources.
- Build the free scraper (RSS first, else homepage links); Firecrawl stays a future option.
- Implement normalization and deduplication.
- Store article records.
- Implement Codex research analysis.

**Exit gate:** research pipeline produces structured content opportunities.

### Phase 9 — Cross-branch pipeline

- Research → ContentBrief.
- ContentBrief → video/image tasks.
- Combine generated assets into a content package.
- Add final review/approval state.

**Exit gate:** the complete pipeline can execute across branches.

## 17. Testing & Acceptance Criteria

| Test level | What to test | Pass condition |
| --- | --- | --- |
| Unit | Adapters, validation, storage, metadata | Deterministic tests pass |
| Integration | Codex/tool → provider | Real provider call succeeds |
| Reference quality | 7–8 identity images → multiple scenes | Person remains acceptably consistent |
| Failure | Invalid key, provider failure, timeout | Clear failed state; no false success |
| Persistence | Output + metadata | Asset can be located and traced to job |
| End-to-end | Request → generation → storage | Complete flow works without manual copying |
| Cross-branch | Research → brief → generation | Structured handoff works |

The first quality gate is not simply whether the image looks good. It is whether the system can repeatedly produce a usable image with the intended person's identity while preserving traceability and reproducibility.

## 18. Open Decisions / Inputs Required

| Decision / input | Why it matters | When needed |
| --- | --- | --- |
| 7–8 person reference images | Determines whether reference conditioning is viable | Before image MVP |
| Exact FLUX model/provider | Determines API/workflow implementation | Phase 1 |
| Reference-image mechanism | Determines identity preservation method | Phase 1 |
| ComfyUI deployment target | Determines infrastructure and API route | Phase 1 |
| Product reference images | Needed for accurate product creatives | Before product workflow |
| Brand guidelines/assets | Needed for brand-style workflows | Phase 5 |
| Source websites | Determines scraper/Actor choice | Before research branch |
| Asset storage provider | Determines persistence/deployment | Phase 6 |
| Database provider | Determines production metadata layer | Phase 6 |
| API access/credits | Subscription does not automatically prove API entitlement | Before each provider integration |

## 19. Working Method: Claude + Codex

Claude's role: senior implementation guide and reviewer. Codex's role: actual coding/building agent. The developer controls credentials, external accounts, and final technical decisions.

```
Claude → Stage instructions
       |
       v
Developer → paste exact implementation prompt into Codex
       |
       v
Codex → inspect → implement → test → report
       |
       v
Developer → show result to Claude
       |
       v
Claude → review → next stage
```

Every Codex implementation prompt should tell Codex to inspect the current repository first, preserve working code, avoid unnecessary rewrites, use environment variables for secrets, run tests, and report changed files and unresolved blockers.

## 20. Definition of Done — Entire Automation

- Codex can select and invoke the three branch workflows.
- Image branch reliably creates brand visuals with reference-based person consistency.
- Video branch can produce UGC, Reels/Shorts, and Podcast content using selected providers.
- Research branch collects configured sources and turns them into structured content opportunities.
- Branches exchange structured ContentBrief, Asset, and Job objects rather than ad-hoc text.
- All provider calls are authenticated securely.
- Long-running jobs have status, retry, timeout, and failure handling.
- Generated outputs are persistently stored and traceable.
- Workflow versions and generation parameters are recorded.
- End-to-end research → content → image/video package can be executed.

This blueprint intentionally leaves certain provider, model, storage, and infrastructure choices as validation gates instead of pretending they are already finalized. That prevents building the wrong integration before the exact requirements and provider capabilities are verified.

## 21. Immediate Next Step

Start with Branch 1. Before building the actual generation workflow, verify the repository/environment, the exact FLUX option, the reference-image mechanism, the ComfyUI route, and whether API or MCP is the cleaner integration. Then build the smallest possible proof-of-concept: one Codex-triggered generation using the person's reference set, followed by output storage and metadata.
