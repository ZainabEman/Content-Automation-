# Platforms and categories

Each category has its own rule in `config/copy_rules.json` `categories.<category>`: `goal`, `address`, `headlineMaxWords`, `bodyMaxWords`, `ctas`, `ctaRequired`, and for the carousel `sentenceCase`. The layout limits (characters, lines, minimum font) are in each variant's `textLimits` in `config/design_directions.json`. The copy review draws the copy once with a stand-in picture and refuses text that doesn't fit.

## The image text (every category)
- **Headline** = the `coreIdea`, the best of the 3 options.
- **Body** = ONE concrete benefit or what-it-does sentence, directly under the headline.
- **Chips** (where the layout has chips) = 3–4 short benefit labels (`chips`). Roman variants always have 3 and a full body line (`roman`).
- **CTA** = from the category's `ctas` list and fit for the brief's service (`ctas.<label>.services`). The icon follows the meaning: a calendar only for booking.
- **Visual** (`copyPlan.visual`) = the benefit in action, one scene with its callouts (`visualCallouts`).
- Detail lives in the caption, not on the image.

## The caption (every category)
- **Shape:** `hook` (line 1), 3–5 `takeaways`, one `question`, optional `closingDe`, then the `cta` line with the link and the hashtags, including #BrandedGenius.
- **Limits** (code): the word range is `CAPTION_MIN_WORDS`/`CAPTION_MAX_WORDS` and `CAPTION_MAX_WORDS_BY_PLATFORM` in `content/quality.py`. Takeaways and hashtags follow `MIN_TAKEAWAYS`/`MAX_TAKEAWAYS` and `MIN_HASHTAGS`/`MAX_HASHTAGS` in `content/brief.py`.
- **Takeaways** teach something usable today, said as the reader's business step, never a checklist for technicians. The caption as a whole needs one concrete element (a channel or tool, a timing, a number, a quote or an example: checked once per caption, not per takeaway). No fixed label in front of the takeaways (such as "Website-Check:"): the dry run refuses a label that starts two or more of them.
- **CTA:** with a verified service, the `cta` names the offer from the `Offer:` line in `brand/services.md` (checked). An insight-only post asks a question instead and makes no sales ask. It works on the platform: Instagram asks for a comment keyword, a save or a DM; Facebook points to the link in the caption.
- **One specific element** from the proof. No invented anecdote.

## LinkedIn (`linkedin_post`, "Sie")
- The hook sits in the first ~140 characters, on one line (before "…mehr anzeigen").
- 1–2-line paragraphs, a business takeaway for decision makers, a soft CTA and the existing word range.
- Hashtags: 3–5, by default 3 (2026-10-22).
- Professional tone: no slang, no emoji.

## Facebook post (`facebook_post`, "Sie")
- Conversational "Sie", and a shorter caption (the lower end of the range).
- An insight with a business takeaway, ending with a question or a soft CTA.

## Facebook ad (`facebook_ad`, "Sie")
- Offer-led: the pain, the offer, the next step. The CTA on the image is required (`ctaRequired`).
- `adFields.primaryText` = the benefit plus the offer plus the next step, in 1–3 short sentences.
- `adFields.headline` and `description` stay within their limits. `ctaButton` comes from `config/meta_cta.json`.
- An ad always sells a verified service, never an insight-only one.

## Instagram carousel (`instagram_carousel`, "du")
- "du"/"dein" on every slide AND in the caption, in sentence case.
- The cover is a trend or provocation hook. Then one idea per slide. The last slide asks for engagement: a question to comment on, or save/share.
- Body length: `bodyMaxWords` on the cover and the last slide; a point slide may use its layout's limit (`bodyMaxWordsBySlide`, the same number as the slide hint), in 2–4 short lines.
- Caption hashtags as above.

## The same topic on several platforms
Write each platform's copy from the same editorial brief, but with its own hook pattern, its own headline and its own first caption line. Never copy and shorten. The copy review flags headlines or captions of one topic (the same research source) at or above `week.similarity`.
