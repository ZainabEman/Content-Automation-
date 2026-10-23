# Short-form YouTube script (about 1 minute)

Write a podcast-style dialogue in spoken German, about 140-160 words (config/youtube.json
formats.short.targetWords).

- Speakers: every paragraph starts with `HOST:` (the AI-generated host: introduces the topic and
  asks) or `ROMAN:` (Roman Traenkle: analyses and explains what it means). Both speak.
- One topic only, always a problem and always about Germany (user decision 2026-10-23:
  short-form is negative, no positive-news topics; a global story only when it clearly hits
  German companies, workers or citizens, and the script says how):
  - negative developments in tech in Germany (failed digital projects, outages, slow
    digitalisation, security incidents, data leaks)
  - AI risks: errors and hallucinations, misuse, fraud, deepfakes and voice cloning, data
    protection, loss of control, AI used wrongly in companies or authorities
  - harm to people and jobs: job losses, surveillance at work, discrimination by algorithms,
    cost to businesses
  - limits and controversies: where AI fails, broken promises, unclear rules (AI Act, DSGVO)
- Structure, in this order:
  1. **Negative hook** (HOST): the problem in one sharp line or question.
  2. **Stat** (ROMAN): one real, sourced number that shows how big it is.
  3. **Points** (HOST asks, ROMAN answers): 2-3 short points on why it happens and who it hits.
  4. **Solution** (ROMAN): what companies or people can do now, concrete and short.
- Serious, not alarmist: no invented drama, no clickbait, no sales pitch.
- Only verified facts from research.txt (fact IDs [F#]); numbers exactly as written. The IDs,
  sources and URLs stay out of the teleprompter file; the storyboard carries the references.
- Address the viewer with "Sie". Short sentences, the verb early, numbers written as spoken.
- Never let Roman claim an experience he did not have.
