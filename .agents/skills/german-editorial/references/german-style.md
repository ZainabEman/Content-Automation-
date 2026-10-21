# German style for business readers

This is business German, not Einfache Sprache: write the way a good German business journalist writes to an owner.

## Sentences
- Keep sentences short and active, one statement each, in subject–verb–object order.
- Caption sentences stay under `style.sentenceMaxWords` (`config/copy_rules.json`). The copy review warns when one is longer.
- Keep both parts of the verb close together. Put the important point first.

## Verbs, not noun chains (Nominalstil)
- "Sie prüfen die Quelle", not "Die Durchführung einer Quellenprüfung erfolgt".
- Three or more -ung/-heit/-keit/-tion nouns in one sentence trigger a warning (`style.nounChainMin`).
- Cut filler words and unnecessary modal verbs ("können", "sollten"). Question every adjective.

## Words
- Prefer concrete nouns and numbers from the proof over buzzwords.
- Use one term per thing. Don't switch between "KI-Assistent", "Bot" and "Agent" for the same tool.
- No unexplained jargon: never use a `jargon` term (`config/copy_rules.json`) in a headline or a chip. In the body, use one only with a plain explanation right after it.
- No anglicism where a common German word exists ("Anwendungsfall", not "Use Case"). Established terms are fine: KI, Chatbot, Team, Workflow, Website (`allowEnglish` in `config/german_quality.json`).
- No filler or empty marketing phrases: `bannedPhrases` in `config/german_quality.json` is the single banned list, and the German check refuses them. Add new ones there, never in a second list.
- Write abbreviations out, unless they are better known than the long form (KI, CRM).

## Correctness
- Use correct umlauts and ß (never ae/oe/ue/ss), and capitalise nouns. The German check refuses known transliterations.
- Use German quotation marks „…“ and the spaced dash " – ", as in the brand references (`brand/copy_examples.json`). Code does not check these.
- Use the category's address (`categories.<category>.address`) in every line of the piece, the caption included. "Sie/Ihr" is always capitalised.
- Don't break a word at a line end. Headlines get no hyphenation.

## Hooks, headlines and CTAs
- Use the patterns and examples in `brand/copy_examples.json` (`patterns`, `examples`; `weak` shows what to avoid).
- **True and covered by the proof.** No clickbait, no fear without a way out, and no implied client results.
- **Never** a headline aimed at technicians ("BROWSER-AGENTEN BRAUCHEN BEDIENBARE SEITEN"), a headline that is just a news title, or an instruction ("Öffnen Sie …").
- Write "Sie"/"du" instead of "wir" wherever possible. Name the reader's gain: time, money, customers, calm or safety.
- No hook pattern more than `week.maxSamePattern` times a week. The week review warns.
- **CTA** = an action verb plus what the reader gets, taken from the category's `ctas` list. "Mehr erfahren" is only a soft CTA for insight posts. Never a CTA that asks for work ("Quelle prüfen").

## Read-aloud test
Read the piece aloud once. If you stumble, run out of breath or would never say it to a customer, rewrite it.
