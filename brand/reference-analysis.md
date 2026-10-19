# Reference analysis: approved Branded Genius graphics (PRD v5 R2.3)

Written 2026-10-19 from the APPROVED company references only (config/brand_refs.json). Every rule
names its source. Competitor material (Phase D R01–R36, C1–C7) is archived and was not used.

Sources (files under `assets/reference/`, git-ignored):
- **Guide** = `brand/guidelines/Branded Genius Brand Style Guide.pdf` (one page, "MARKEN STYLEGUIDE").
- **A01–A06** = `creative/facebook_ads/01.jpg … 06.jpg` (1254×1254, all with the Branded Genius wordmark).
- **K01–K11** = `creative/carousels/carousel_01 … carousel_11` (MP4 slides, stills in `_frames/`, 960×960, 8 slides each, logo on slide 8).
- **Designer** = the graphic designer's prompt (PRD R3). Her own output files: **not found** in the references folder.

Priority (R2.1): Guide > official assets > A/K references > Designer prompt.

## 1. Palette

| Rule | Source |
|---|---|
| Brand colours only: Royal Blue #004BA0, Sky Blue #69BFF8, Medium Gray #969595, White #FFFFFF; blue gradient Royal→Sky ("BRANDED"), silver gradient Gray→White ("GENIUS") | Guide, Farbauswahl |
| Highlight words in Sky Blue on dark ("UNSERE **KI NICHT.**", "**MEHR WACHSTUM.**") | A01, A02, A04, A06 |
| Highlight words in a saturated electric blue (measured ≈ #147BCC–#2569B4) on dark | K01, K05, K09, K10 (measured medians of saturated pixels) |
| Backgrounds near-black navy (measured darkest-40 % medians #000414, #03162B, #010F29, #00040E, #010310, #010A1B; carousels #000000–#01000C) with blue neon glow | A01–A06, K01–K11 |
| Light area: a white/light-grey diagonal sweep in the lower right | A02 |

**Implemented:** app fills use the 4 guide tokens only (D-1 kept); dark backgrounds come from the generated picture (the designer prompt asks for the references' near-black look) under a Royal Blue scrim; accent words Sky Blue; one light treatment (silver gradient) from A02.

## 2. Typography and hierarchy

| Rule | Source |
|---|---|
| Heading Futura Bold, sub-head Futura Medium, Good Times only for the logo | Guide, Typografie |
| Headlines bold, often all caps, 2–4 lines, 1–2 words highlighted | A01, A03, A04, A05, A06; K02, K03, K05, K06 |
| Sentence-case headlines with blue keywords and a short blue accent rule under them | K09, K10, K01 |
| Sub-line: small, medium weight, sometimes all caps, white | A01 (caps), A02, A04, K02 |
| Hierarchy: headline → one supporting line → (icons / CTA) | A01–A06 |
| Big blue numeral before a point headline ("1. LEADS WERDEN…") | K02 |

**Implemented:** Jost (stand-in until licensed Futura files are added); headline 54–80 px, sub 28–30 px; caps in ads/FB/LI panel layouts, sentence case in CS-1 and LI-1; accent rule in CS-1, CS-3, LI-1; numeral field in CS-2.

## 3. Composition, placement, spacing

| Rule | Source |
|---|---|
| Text block in the left half, main visual in the right half | A01, A04, A05, A06; K02–K11 |
| Framed panel (rounded rectangle, thin blue outline) behind the text | A01, A06 |
| Headline panel top left over a before/after picture | A02 |
| Centred cover headline over a full-bleed visual | K01, K03 |
| Row of circular icons with short labels under the text | A04, A05 |
| Generous margins; text never touches the edge | all |
| Dot grids in corners, thin arcs, a particle wave along the bottom | K05–K11 (dots, arcs), K01, K08–K11 (wave) |

## 4. Logo

| Rule | Source |
|---|---|
| Wordmark top left or top right, small, never redrawn; white lettering on dark | A01–A06; Guide (Dunkles Logo) |
| Carousels: logo only on the last slide, top right (monogram + wordmark) | K01–K11 slide 8 |
| LinkedIn: logo at a side corner | Designer prompt |

**Implemented:** official file pasted by code (hash-checked), corner zones only; carousel logo only on the closing layout (loader + design check).

## 5. CTA and engagement

| Rule | Source |
|---|---|
| CTA pill bottom right: rounded, blue outline, white text, arrow or calendar icon | A01–A06 |
| Chevrons ">>>>" decoration bottom left | A01 |
| Closing carousel slide: question + "Liken / Teilen / Speichern" icon row in a framed bar | K01, K02, K03, K09, K10 |
| Slide counter pill "01/07" top right | K01–K03 → **not reproduced** (PRD R4) |

## 6. Supporting graphics

| Rule | Source |
|---|---|
| 3D neon objects on a pedestal under a spotlight (clipboard, phone, robot, target) | K02, K03 |
| Neon line icons / icon networks | K05, K06, K09 |
| Stock business people (not Roman) in ads | A02, A03, A06 → replaced by Roman via his LoRA (FB-R1, FA-R1, LI-R1) |

## 7. Layout variants derived (config/design_directions.json)

| Category | Variant | Treatment | From |
|---|---|---|---|
| Instagram carousel 1:1, 5–6 slides | CS-1 Neon Statement | dark_wave | K09, K11, K10 |
| | CS-2 Numbered Points | dark_spotlight | K02, K03 |
| | CS-3 Centred Cover | dark_center | K01, K03 |
| | CS-4 Condensed Blocks | dark_arc | K05, K06 |
| Facebook post 4:5 | FB-1 Panel + Visual | dark_panel | A01, A06 |
| | FB-2 Before / After | dark_split | A02 |
| | FB-3 Icon Row | dark_icons | A04, A05 |
| | FB-4 Light Sweep | light_sweep | A02 |
| | FB-R1 Founder | dark_founder | A03, A06 |
| Facebook ad 4:5 | FA-1 Offer Panel, FA-2 Before / After Ad, FA-3 Feature Ad, FA-R1 Founder Ad | as above | A01–A06 |
| LinkedIn 3:4 | LI-1 Headline + Visual, LI-2 Panel + Visual, LI-3 Icon Row, LI-4 Light Sweep, LI-R1 Founder | dark_glow, dark_panel, dark_icons, light_sweep, dark_founder | K09, A01–A06, Designer |

## 8. Disagreements (the guide wins; for Roman to decide)

1. **Background colour.** Every approved graphic uses a near-black navy background; the guide lists no such colour, and decision D-1 (2026-10-17) says dark designs are Royal Blue. Kept: app-drawn fills are Royal Blue; the generated picture carries the near-black look. Result: v5 designs read bluer than the references (see `outputs/previews/design/v5_vs_references.png`). Question: allow a near-black dark token (e.g. a Royal Blue shade) as in the references?
2. **Accent blue.** The carousels use a brighter electric blue (≈ #147BCC) that is between Royal Blue and Sky Blue; the guide has neither. Kept: Sky Blue.
3. **Headline font.** The references use condensed and geometric sans faces that are not Futura in places (K05, K06 condensed). Kept: Futura (Jost stand-in), the guide's font.
4. **Form of address.** Carousels say "du" (K04, K07–K11), ads say "Sie" (A02, A06). Kept: "Sie" (PRD Q3 default); "du" is a warning in the German check.
5. **Slide count.** References have 8 slides; PRD R4 says 5–6. Kept: 5–6.
6. **Carousel size.** References are 1:1 (960×960 stills); kept 1:1 at 1080×1080 (PRD R4).
