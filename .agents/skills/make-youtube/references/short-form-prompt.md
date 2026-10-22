# Short-form YouTube script (about 1 minute)

Write a podcast-style dialogue in spoken German, about 140-160 words (config/youtube.json
formats.short.targetWords).

- Speakers: every paragraph starts with `HOST:` (the AI-generated host: introduces the topic and
  asks) or `ROMAN:` (Roman Traenkle: analyses and explains what it means). Adapt the balance to
  the topic; both speak.
- One topic only. Strong hook in the first line (a striking, sourced fact or a direct question).
- Topics: AI news, AI problems in Germany (business, work, society), the impact on people and
  jobs, risks, limits, controversies, positive developments.
- End naturally: a takeaway, a question to the viewer or a strong statement. No sales pitch.
- Only verified facts from research.txt (fact IDs [F#]); numbers exactly as written. The IDs,
  sources and URLs stay out of the teleprompter file; the storyboard carries the references.
- Address the viewer with "Sie". Short sentences, the verb early, numbers written as spoken.
- Never let Roman claim an experience he did not have.
