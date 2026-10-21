# Editorial brief (`copyPlan.editorial`)

Write it before any headline. Each field is one short line in German or English (the reader never sees it). The copy review prints it above the copy.

| Field | Question | Good | Weak |
|---|---|---|---|
| `audience` | Which German business reader exactly? | "Inhaber eines Steuerbüros mit 8 Mitarbeitenden" | "Unternehmen" |
| `problem` | What is their situation, in their own words? | "Anfragen kommen abends rein und bleiben bis morgen liegen." | "Lead-Management ist ineffizient." |
| `coreIdea` | The one idea, in one sentence | "Wer zuerst antwortet, bekommt den Auftrag." | "KI ist wichtig." |
| `proof.fact` + `proof.source` | What makes it true? | the source fact, with the article ID it comes from | "Studien zeigen …" without a source |
| `objection` | What will the reader doubt? | "Mein Kunde merkt doch, dass das ein Bot ist." | (empty) |
| `action` | What should they do next? | "Die KI-Potenzialanalyse anfragen" / "die eigene Antwortzeit messen" | "Mehr erfahren" |

**Proof sources** (checked by the copy check, `editorialBrief` in `config/copy_rules.json`): a cited article ID (`sourceArticleIds` or an insight's `source`), a link listed in `research.md`, `proof.md` (`brand/proof.md`), or `service:<id>` of a verified service in `config/services.json`.

**From the brief to the copy:**
- `angle` (the c2eedff reader angle) answers "What does this mean for your business, and what should you do?" (news), or "What pain does this remove, and what do you gain?" (service).
- The headline carries the `coreIdea`.
- The body or the caption meets the `objection`.
- The CTA is the `action`.
- One specific element (a number, a case or an opinion) comes from `proof`. If the proof has no number, write no number.
- A news source is never just retold. Translate it into the reader's situation. An instruction for website teams ("Öffnen Sie die konkrete URL") is not a business takeaway.
