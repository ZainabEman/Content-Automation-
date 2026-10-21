# Review rubric

There are two scores, both written into `brief.json` and shown in the copy review.

## 1. Headline options (`copyPlan.headlineOptions[].score`, 0–6)
`rubric` in `config/copy_rules.json`, one point per criterion. Use it to pick the best of the 3 headlines. The best one becomes the headline and must reach `minScore`.

## 2. The whole piece (`copyPlan.review.scores`, 0–2 per criterion)
`pieceRubric.criteria` in `config/copy_rules.json`. Score the graphic and the caption together: 0 = missing, 1 = partly, 2 = clearly.

| Key | 2 means |
|---|---|
| `singleIdea` | the reader can repeat the one idea (the editorial `coreIdea`) in one sentence |
| `relevance` | it matters to this German business reader: time, money, customers, risk or calm |
| `specificity` | it has one real number, case or opinion from the proof, and no line that fits any topic |
| `naturalGerman` | it reads like German business writing (german-style.md) |
| `hook` | the first words make the reader stop, and the pattern isn't overused this week |
| `truth` | every fact, number, name and promise is covered by the proof or the verified services |
| `ctaFit` | the action verb plus the gain fits the piece and the service |
| `platformFit` | it follows platforms.md and differs from the same topic elsewhere |

**The bar:** `pieceRubric.minTotal`, no criterion below `minEach`, and the `mustBeFull` criteria (truth) at 2. Below the bar the copy check blocks with "rewrite the piece". You get one rewrite; if it still fails, the review shows `STOPPED` and the user decides. Nothing is dropped silently. Put the reason for any score below 2 in `copyPlan.review.why`.

Score honestly: Roman's copy approval is the final gate, and a lenient self-score only moves the problem to him.

## Rewrite at once, whatever the score
- an invented customer story, client, result, price or quote
- a number, year, organisation or study the proof doesn't cover ("unbelegte Aussage")
- an instruction-style headline for technicians, or a bare news title
- the wrong address ("Sie" in a carousel, "du" anywhere else), in the graphic or the caption
- a CTA that asks for work ("Quelle prüfen") or sells in an insight-only post
- fear without a way out, or engagement bait ("Kommentiere JA, wenn …")
- the same headline or caption as the same topic on another platform
