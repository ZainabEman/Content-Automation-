# Short-form YouTube script (about 1 minute)

Write a podcast-style clip in spoken German, about 150-180 words (config/youtube.json
formats.short.targetWords). It must sound like a real conversation that someone cut out of a
longer episode, not like a news report read aloud. The style comes from the English reels in
`short-form-style.md` (read it before writing): take their rhythm, hooks and structure, never
their sentences or facts.

## Speakers

Every paragraph starts with `HOST:` or `ROMAN:`. Both speak.

- `HOST:` (the AI-generated host) speaks for the viewer: short, sharp questions, honest
  reactions ("Moment. Wirklich?", "Das ist doch verrückt."), sometimes a dry joke. HOST never
  explains the topic; HOST pulls the story out of Roman.
- `ROMAN:` (Roman Traenkle) tells the story and explains what it means. Calm, sure of himself,
  concrete. He tells real cases as stories ("Da gab es diesen Fall …"), never as his own
  experience.

## Topics

AI only, always a problem or a risk, never good news (user decision 2026-10-24).

- **German cases first**: AI fraud and deepfakes (fake videos of known Germans selling
  investments or miracle cures), chatbots that mislead customers and the court rulings that
  follow, wrong AI answers about companies, staff pasting confidential data into AI tools,
  fake AI testimonials and ads, AI-powered phishing and CEO fraud, AI used wrongly in companies
  or authorities. Seed list: `short-form-topics.md`.
- **Global AI stories are allowed** (safety tests where models blackmail or refuse to shut
  down, AI companions and children, warnings from AI pioneers) when the script says in one
  line what they mean for Germany: for German companies, workers, parents or customers.

## Structure (in this order)

1. **Hook, in the first 2 seconds** (HOST or ROMAN, at most 15 words): the most surprising
   fact, the twist or a question nobody can ignore. Never start with a greeting, the topic's
   name or "Heute sprechen wir über …". Good patterns:
   - shocking fact: "Der Milliardär hat das nie gesagt. Trotzdem haben Leute ihm Geld
     überwiesen."
   - what-would-you-do: "Was würdest du tun, wenn dein Chef dich anruft und es gar nicht dein
     Chef ist?"
   - contradiction: "Die Firma sagt: Das war nicht ich, das war der Chatbot. Das Gericht sagt:
     Doch."
2. **Story** (ROMAN, HOST cuts in): the real case, told like a story: who, what happened, the
   moment it went wrong. One concrete detail the viewer remembers (a name, a sum, a quote).
3. **Escalation** (HOST asks, ROMAN answers, 2-3 turns): each turn adds something worse or
   bigger: one sourced number, who else is hit, why it keeps happening. HOST reacts in a
   few words.
4. **Twist or meaning** (ROMAN): the turn that makes it personal: "Und genau das kann jedem
   Unternehmen passieren." For a global story: what it means for Germany.
5. **Short tip** (ROMAN, one or two sentences): one concrete thing to do now. No list, no
   lecture, no sales pitch, no mention of Branded Genius.
6. **Open question** (HOST or ROMAN, last line): the big question left hanging, one that makes
   people comment: "Würdest du den Unterschied noch erkennen?"

## Voice

- Address the viewer with **"du"** (config formats.short.address), casual like German Reels and
  Shorts, never childish. Roman and HOST say "du" to each other too.
- Talk like people talk: short sentences, half sentences are fine ("Zwei Millionen. Einfach
  weg."), the verb early, contractions where natural ("gibt's", "ist's", "hab"). One thought
  per sentence. Vary the length: a long sentence, then a very short one.
- Suspense: hold back the answer for one beat ("Und dann kam die zweite E-Mail."), use "Und
  jetzt kommt's", "Das Verrückte ist", "Aber es wird noch schlimmer".
- Light humour where the topic offers it, dry irony aimed at the situation, never at victims:
  "'Unser Chatbot hat das erfunden' ist jetzt nicht die beste Kundenservice-Strategie."
- Emotion is allowed and wanted (surprise, anger, worry), the facts stay exact: no invented
  drama, no "experts say" without a source, no doom beyond what the sources show.
- No AI phrasing: no "In der heutigen Zeit", "Tauchen wir ein", "spannend", "revolutionär",
  "Gamechanger", no lists of three for rhythm only.

## Facts

- Only verified facts from research.txt (fact IDs [F#]); numbers and quotes exactly as
  written. Name the case and the source in words where it builds trust ("Laut einer
  KPMG-Studie …"). The IDs, URLs and source notes stay out of the teleprompter file; the
  storyboard carries the references.
- A case the research could not verify is left out or clearly framed as a hypothetical
  ("Stell dir vor …"), never told as real.
- Never let Roman claim an experience he did not have.
