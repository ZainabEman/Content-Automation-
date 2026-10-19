"""Content checks on brief.json, run by the dry run (nothing is made while one fails).

- Carousel story: hook -> problem -> steps or insights -> example or result -> cta, 6-8 slides.
- Post formats (config/post_formats.json): only the chosen format's fields, all filled; a
  carousel runs cover -> body -> final with alt text per slide; big numbers only from the
  cited research.
- Middle slides teach something usable today: specific, never generic, and the step, insight
  and example slides show the automation concretely (a channel or tool and a timing).
- Posts: the supporting line and the key points are specific too.
- Insights: at least 6 specific findings from the research, each with its source; their
  numbers must be in the article they cite.
- Captions: 120-200 words, 3-5 takeaways, a question, the CTA with the offer.
- Numbers that read as results come only from brand/proof.md or the cited research.
"""

import re
from collections.abc import Iterable, Mapping

from content_automation.content.brief import (
    MIN_INSIGHTS,
    Caption,
    ContentBrief,
    ImageSlot,
    SlideSlot,
)
from content_automation.content.formats import (
    BANNED,
    FormatCatalog,
    FormatError,
    copy_problems,
)
from content_automation.content.relevance import cta_problems, unverified_claims
from content_automation.references.services import ServiceCatalog
from content_automation.workflows.design_system import DesignSystem

SAME_POINT = 0.6  # tips whose key words overlap this much make the same point
CAPTION_MIN_WORDS, CAPTION_MAX_WORDS = 120, 200
CAPTION_MAX_WORDS_BY_PLATFORM = {"linkedin": 250}  # LinkedIn shows longer professional text
_WORD = re.compile(r"[a-z0-9äöüß]+")
_STOP = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "for", "from", "get", "how", "in",
    "into", "is", "it", "its", "more", "of", "on", "or", "our", "so", "than", "that", "the",
    "their", "them", "they", "this", "to", "up", "use", "with", "you", "your",
    # v5: German copy (the default language)
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "und",
    "oder", "mit", "für", "von", "zu", "zum", "zur", "im", "ist", "sind", "sie", "ihr", "ihre",
    "ihren", "ihrem", "wir", "unser", "unsere", "auf", "aus", "bei", "nicht", "noch", "mehr",
    "wie", "was", "als", "auch", "es", "sich", "dass", "am", "um", "nur",
})
_TIP_LIKE = re.compile(r"^\s*(?:tip|step)\s*\d|^\s*\d+\s*[.)]", re.IGNORECASE)
# Numbers that read as results: percentages, multiples, money, counts of business outcomes.
_RESULT = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|percent\b|prozent\b|x\b|×|times\b|mal\b)"
    r"|[€$£]\s*\d+(?:[.,]\d+)*|\d+(?:[.,]\d+)*\s*(?:€|eur\b|euros?\b|dollars?\b)"
    r"|\d+(?:[.,]\d+)*\s+(?:more\s+|new\s+|extra\s+|mehr\s+|neue\s+|zusätzliche\s+)?"
    r"(?:leads|clients|customers|sales|bookings|appointments|calls|hours|reviews|patients|orders"
    r"|kunden|kundinnen|buchungen|termine|anrufe|stunden|bewertungen|patienten|bestellungen"
    r"|anfragen)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# "within 5 minutes", "after 24 hours": a timing, not a result
_TIMING_BEFORE = re.compile(r"(?:within|after|before|every|each|per|next|first|in the first"
                            r"|innerhalb von|innerhalb|nach|vor|alle|jede|jeden|pro|"
                            r"in den ersten)\s+$", re.IGNORECASE)

# What makes a line usable: a channel or tool (who sends through what) and a timing (when).
CHANNELS = (
    "sms", "text message", "texts", "email", "e-mail", "emails", "whatsapp", "messenger", "dm",
    "dms", "instagram", "facebook", "chat", "chatbot", "bot", "website", "web form", "form",
    "landing page", "crm", "hubspot", "pipedrive", "salesforce", "zapier", "make.com",
    "calendly", "calendar", "booking link", "phone", "call", "calls", "voicemail", "missed call",
    "slack", "spreadsheet", "template", "autoresponder", "auto-reply", "tag", "tags", "pipeline",
    "inbox", "notification", "reminder", "sequence", "workflow", "trigger", "webhook",
    "google", "zillow", "portal", "listing alert", "lead form", "voice agent", "ai assistant",
    "review request", "survey", "newsletter", "ads",
    # v5: German copy (the default language)
    "telefon", "anruf", "anrufe", "rückruf", "anrufbeantworter", "mailbox", "webseite",
    "kontaktformular", "formular", "landingpage", "kalender", "buchungslink", "terminbuchung",
    "posteingang", "benachrichtigung", "erinnerung", "vorlage", "tabelle", "ki-assistent",
    "sprachassistent", "bewertungsanfrage", "umfrage", "anzeigen", "online-termin", "ki-agent",
)
TIMINGS = (  # real times: they make a line specific
    "minute", "minutes", "min", "hour", "hours", "day", "days", "week", "weeks", "month",
    "months", "morning", "evening", "night", "overnight", "same day", "same-day", "24/7",
    "weekend", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "daily", "weekly", "instantly", "immediately", "tomorrow", "today",
    # v5: German copy
    "minute", "minuten", "stunde", "stunden", "tag", "tage", "tagen", "woche", "wochen",
    "monat", "monate", "monaten", "morgens", "abends", "nachts", "über nacht", "wochenende",
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag", "täglich",
    "wöchentlich", "sofort", "heute", "rund um die uhr",
)
SEQUENCE = ("within", "after", "before", "every", "once", "when", "until", "then",  # "when" only
            "innerhalb", "nach", "sobald", "bevor", "jede", "jeden", "bis", "dann")
# Empty marketing phrases: a line with one of them is generic, whatever else it says.
BUZZWORDS = (
    "game changer", "game-changer", "next level", "unlock", "supercharge", "revolutionize",
    "revolutionise", "seamless", "cutting-edge", "cutting edge", "world-class", "fast-paced",
    "sets the next step", "take your business", "skyrocket", "effortless",
    # v5: German (config/german_quality.json has the full banned list for the German check)
    "gamechanger", "nächste level", "nächsten level", "revolutionär", "revolutionieren",
    "bahnbrechend", "nahtlos", "mühelos", "schnelllebigen",
)
_QUOTED = re.compile(r"[\"“”‘’]|'[^']{3,}'")


def _has(text: str, words: Iterable[str]) -> bool:
    low = text.lower()
    return any(re.search(rf"(?<![a-zäöüß]){re.escape(word)}(?![a-zäöüß])", low) for word in words)


def generic_reason(text: str) -> str | None:
    """Why a line is too generic to teach anything (None: it is specific)."""
    if _has(text, BUZZWORDS):
        return "uses an empty marketing phrase"
    if re.search(r"\d", text) or _QUOTED.search(text):
        return None
    if _has(text, CHANNELS) or _has(text, TIMINGS):
        return None
    return "says nothing specific (no channel or tool, timing, number or example wording)"


def automation_reason(texts: Iterable[str]) -> str | None:
    """A step, insight or example shows who sends what, when and through which channel."""
    joined = " ".join(texts)
    missing = []
    if not _has(joined, CHANNELS):
        missing.append("the channel or tool")
    if not (_has(joined, TIMINGS) or _has(joined, SEQUENCE) or re.search(r"\d", joined)):
        missing.append("when it happens")
    return f"show the automation concretely: name {' and '.join(missing)}" if missing else None


def _key_words(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if word not in _STOP}


def _overlap(first: set[str], second: set[str]) -> float:
    return len(first & second) / len(first | second) if first and second else 0.0


def _carousels(brief: ContentBrief) -> Iterable[tuple[str, ImageSlot]]:
    for name in ("carousel", "post"):
        slot: ImageSlot | None = getattr(brief, name)
        if slot is not None and slot.format == "carousel" and slot.slides:
            yield name, slot


def _slide_texts(slide: SlideSlot) -> list[str]:
    texts = [slide.headline, slide.subheadline or ""]
    for value in slide.copy_text.values():
        texts += value if isinstance(value, list) else [value]
    texts += [bubble.text for bubble in slide.chat] + list(slide.diagram) + list(slide.checklist)
    if slide.before_after is not None:
        texts += [slide.before_after.before, slide.before_after.after]
    return texts


def _story_problems(name: str, slides: list[SlideSlot]) -> list[str]:
    """hook -> problem -> steps or insights -> example or result -> cta."""
    wanted: list[tuple[str, ...]] = [("hook",), ("problem",)]
    wanted += [("step", "insight")] * (len(slides) - 4)
    wanted += [("example", "result"), ("cta",)]
    problems = []
    for number, (slide, allowed) in enumerate(zip(slides, wanted, strict=False), start=1):
        if slide.role is None:
            problems.append(
                f'{name}.slides[{number}].role: set it ("{" or ".join(allowed)}"); the story runs '
                "hook -> problem -> steps or insights -> example or result -> cta"
            )
        elif slide.role not in allowed:
            problems.append(
                f'{name}.slides[{number}].role is "{slide.role}" but this place in the story is '
                f'{" or ".join(allowed)} (hook -> problem -> steps or insights -> example or '
                "result -> cta)"
            )
    return problems


def carousel_problems(
    brief: ContentBrief,
    system: DesignSystem,
    platforms: dict[str, str] | None = None,
    offer: str = "",
) -> list[str]:
    """platforms: the platform of each brief part (from its deliverable); default the brief's.
    offer: the services.md offer the last slide's call to action must name."""
    platforms = platforms or {}
    problems = []
    for name, slot in _carousels(brief):
        if slot.templated:
            continue  # format_problems or direction_problems
        hook, middle, last = slot.slides[0], slot.slides[1:-1], slot.slides[-1]
        problems += _story_problems(name, slot.slides)
        if not slot.audience_line:
            problems.append(
                f'{name}.audienceLine: the hook names the audience, e.g. "FOR DENTAL PRACTICES"'
            )
        if (hook.visual or hook.chat or hook.diagram or hook.checklist or hook.before_after
                or _TIP_LIKE.match(hook.headline)):
            problems.append(
                f"{name}.slides[1] is the hook: it names the problem or the promise and carries "
                "no tip (no tip text or visual)"
            )
        if hook.subheadline and (reason := generic_reason(hook.subheadline)):
            problems.append(f'{name}.slides[1].subheadline "{hook.subheadline}": {reason}')
        for number, slide in enumerate(middle, start=2):
            where = f"{name}.slides[{number}]"
            line = slide.subheadline or ""
            reason = generic_reason(line) if line else "give the concrete fact or action"
            if reason:
                problems.append(f'{where}.subheadline "{line}": {reason}')
            if slide.role in ("step", "insight", "example"):
                missing = automation_reason(_slide_texts(slide))
                if missing:
                    problems.append(f"{where}: {missing} (who sends what, when, through which "
                                    "channel)")
        words = [_key_words(f"{tip.headline} {tip.subheadline or ''}") for tip in middle]
        for first in range(len(middle)):
            for second in range(first + 1, len(middle)):
                if _overlap(words[first], words[second]) >= SAME_POINT:
                    problems.append(
                        f"{name}.slides[{first + 2}] and slides[{second + 2}] make the same "
                        "point: give each slide its own step in the story"
                    )
        rule = system.cta_rules.get(platforms.get(name, brief.platform))
        cta = (last.cta or "").lower()
        fits = rule is None or not cta or (
            not any(word in cta for word in rule.avoid)
            and any(re.search(rf"\b{re.escape(word)}\b", cta) for word in rule.require)
        )
        if rule is not None and not fits:
            problems.append(f'{name}.slides[{len(slot.slides)}].cta "{last.cta}": {rule.use}')
        label = offer_label(offer)
        last_text = f"{last.headline} {last.cta or ''}".lower()
        if label and label.lower() not in last_text:
            problems.append(
                f'{name}.slides[{len(slot.slides)}]: the call to action names the offer '
                f'"{label}" (from brand/services.md)'
            )
    return problems


def format_problems(
    brief: ContentBrief, catalog: FormatCatalog, research: Iterable[str]
) -> list[str]:
    """Post formats: only the chosen format's fields, all filled; a carousel runs cover ->
    body -> final with an illustration and alt text per slide; a big number only from the
    cited research."""
    texts = list(research)
    problems: list[str] = []
    for name in ("post", "carousel"):
        slot: ImageSlot | None = getattr(brief, name)
        if slot is None or not slot.post_format:
            continue
        try:
            chosen = catalog.get(slot.post_format)
        except FormatError as error:
            problems.append(f"{name}.postFormat: {error}")
            continue
        if chosen.slides is None:
            if slot.slides:
                problems.append(f"{name}.slides: {chosen.id} is one image; remove the slides")
            problems += copy_problems(chosen, slot.copy_text, name, research=texts)
            problems += _concrete_problems(slot.copy_text, f"{name}.copy")
            continue
        low, high = chosen.slides
        if not low <= len(slot.slides) <= high:
            problems.append(f"{name}.slides: {chosen.id} has {low}-{high} slides, found "
                            f"{len(slot.slides)}")
        for number, slide in enumerate(slot.slides, start=1):
            where = f"{name}.slides[{number}]"
            wanted = "cover" if number == 1 else "final" if number == len(slot.slides) else "body"
            if slide.type != wanted:
                problems.append(f'{where}.type must be "{wanted}" (cover, body slides, final)')
                continue
            problems += copy_problems(chosen, slide.copy_text, where, slide_type=wanted,
                                      research=texts)
            if wanted == "body":
                problems += _concrete_problems(slide.copy_text, f"{where}.copy")
            if chosen.canvas(wanted)[0] is not None and not (slide.illustration or "").strip():
                problems.append(f"{where}.illustration: what the picture shows (a place or "
                                "objects, no text)")
            if not (slide.alt_text or "").strip():
                problems.append(f"{where}.altText: what the slide shows and says, for screen "
                                "readers")
    return problems


_NOT_SHOWN = ("illustration", "source", "icon")


def _copy_values(copy: Mapping[str, object]) -> list[str]:
    """The texts of a format's copy a reader sees."""
    found: list[str] = []
    for name, value in copy.items():
        if name not in _NOT_SHOWN:
            found += [str(item) for item in (value if isinstance(value, list) else [value])
                      if isinstance(item, str) and item.strip()]
    return found


def _concrete_problems(copy: Mapping[str, object], where: str) -> list[str]:
    """No generic post or slide: one concrete example or sourced fact (a number, a tool or
    channel, a timing or example wording) in its copy."""
    texts = _copy_values(copy)
    if not texts:
        return []
    reason = generic_reason(" ".join(texts))
    return [f"{where}: {reason}; give one concrete example or sourced fact"] if reason else []


def banned_problems(brief: ContentBrief) -> list[str]:
    """Words that are never used: SME marketers, leverage, unlock, practical sequence."""
    problems = []
    for where, text in _texts(brief):
        problems += [f'{where}: "{found.group(0)}" is banned; say it plainly'
                     for found in BANNED.finditer(text)]
    return problems


def post_problems(brief: ContentBrief) -> list[str]:
    """A post's supporting line and key points are specific."""
    problems = []
    for name in ("post", "ad"):
        slot: ImageSlot | None = getattr(brief, name)
        if slot is None or slot.format == "carousel":
            continue
        for field, text in [("subheadline", slot.subheadline or "")] + [
            (f"points[{n}]", point) for n, point in enumerate(slot.points, start=1)
        ]:
            reason = generic_reason(text) if text else None
            if reason:
                problems.append(f'{name}.{field} "{text}": {reason}')
    return problems


def offer_label(offer: str) -> str:
    """The name of the offer: "Free consultation call - book at ..." -> "Free consultation call"."""
    return re.split(r"\s+[-–—]\s+", offer.strip(), maxsplit=1)[0].strip()


def caption_words(caption: Caption, cta: str) -> int:
    texts = [caption.hook, *caption.takeaways, caption.question, cta]
    return sum(len(text.split()) for text in texts)


def caption_problems(
    brief: ContentBrief, offer: str = "", platforms: dict[str, str] | None = None
) -> list[str]:
    """Captions of 120-200 words (LinkedIn 120-250, hook on one line); the CTA names the
    offer from services.md. platforms: deliverable -> platform (default: the brief's)."""
    captions = {f"captions.{key}": value for key, value in brief.captions.items()}
    if brief.caption is not None:
        captions["caption"] = brief.caption
    problems = []
    for where, caption in captions.items():
        platform = (platforms or {}).get(where.removeprefix("captions."), brief.platform)
        maximum = CAPTION_MAX_WORDS_BY_PLATFORM.get(platform, CAPTION_MAX_WORDS)
        count = caption_words(caption, brief.cta)
        if not CAPTION_MIN_WORDS <= count <= maximum:
            problems.append(
                f"{where}: {count} words (hook, takeaways, question and cta); write "
                f"{CAPTION_MIN_WORDS}-{maximum}"
            )
        if platform == "linkedin" and "\n" in caption.hook.strip():
            problems.append(f"{where}.hook: one line (LinkedIn shows it before \"see more\")")
        for number, takeaway in enumerate(caption.takeaways, start=1):
            reason = generic_reason(takeaway)
            if reason:
                problems.append(f'{where}.takeaways[{number}] "{takeaway}": {reason}')
    label = offer_label(offer)
    if label and label.lower() not in brief.cta.lower():
        problems.append(f'cta: name the offer "{label}" (from brand/services.md)')
    return problems


def insight_problems(
    brief: ContentBrief,
    research_md: str,
    articles: dict[str, str],
) -> list[str]:
    """At least 6 specific insights, each with its source; their numbers are in that source.

    articles: article ID -> its text (title, summary, content) for the IDs the brief can cite.
    """
    problems = []
    if len(brief.insights) < MIN_INSIGHTS:
        problems.append(
            f"insights: list at least {MIN_INSIGHTS} specific findings from the research (actions, "
            f"how-to steps, example wording, timings, tools, sourced figures); found "
            f"{len(brief.insights)}"
        )
    for number, insight in enumerate(brief.insights, start=1):
        where = f"insights[{number}]"
        source = insight.source.strip()
        text = articles.get(source)
        if text is None and not (source.startswith("http") and source in research_md):
            problems.append(
                f'{where}.source "{source}": use a research article ID (research.md) or a link '
                "listed in research.md"
            )
        reason = generic_reason(insight.text)
        if reason:
            problems.append(f'{where} "{insight.text}": {reason}')
        if text is not None:
            missing = [n for n in _NUMBER.findall(insight.text) if n not in _NUMBER.findall(text)]
            if missing:
                problems.append(
                    f'{where}: the number(s) {", ".join(missing)} are not in article {source}; '
                    "a figure must be written in the source it cites"
                )
    return problems


def _texts(brief: ContentBrief) -> Iterable[tuple[str, str]]:
    """Every text a reader sees, with where it is."""
    for name in ("post", "carousel", "ad"):
        slot: ImageSlot | None = getattr(brief, name)
        if slot is None:
            continue
        fields = {"headline": slot.headline, "subheadline": slot.subheadline, "cta": slot.cta,
                  "audienceLine": slot.audience_line}
        for field, value in fields.items():
            if value:
                yield f"{name}.{field}", value
        for index, point in enumerate([*slot.points, *slot.steps], start=1):
            yield f"{name}.points[{index}]", point
        for value in _copy_values(slot.copy_text):
            yield f"{name}.copy", value
        if slot.alt_text:  # v5 R7.4
            yield f"{name}.altText", slot.alt_text
        if slot.ad_fields is not None:  # v5: the Facebook ad's own texts (R4)
            for field in ("primary_text", "headline", "description"):
                value = getattr(slot.ad_fields, field)
                if value:
                    yield f"{name}.adFields.{field}", value
        for number, slide in enumerate(slot.slides, start=1):
            for value in _slide_texts(slide) + [slide.cta or ""] + _copy_values(slide.copy_text):
                if value:
                    yield f"{name}.slides[{number}]", value
    for key, caption in brief.captions.items():
        for value in (caption.hook, *caption.takeaways, caption.question,
                      caption.closing_de or ""):
            yield f"captions.{key}", value
    if brief.caption is not None:
        for value in (brief.caption.hook, *brief.caption.takeaways, brief.caption.question,
                      brief.caption.closing_de or ""):
            yield "caption", value
    yield "cta", brief.cta
    if brief.reel is not None:
        yield "reel.hook", brief.reel.hook
        yield "reel.script", brief.reel.script
        for scene in brief.reel.scenes:
            if scene.on_screen_text:
                yield "reel.onScreenText", scene.on_screen_text
            if scene.type == "avatar":
                yield "reel.avatar", scene.prompt


def reader_texts(brief: ContentBrief) -> list[tuple[str, str]]:
    """Every text a reader sees, with where it is (also for the German check, v5 R1.6)."""
    return list(_texts(brief))


def service_problems(brief: ContentBrief, services: ServiceCatalog) -> list[str]:
    """Phase D: only verified services are claimed; an insight-only post makes no sales ask."""
    return unverified_claims(_texts(brief), services) + cta_problems(brief.service, brief.cta)


def proof_problems(brief: ContentBrief, proof: str, research: Iterable[str]) -> list[str]:
    """Result-like numbers must appear in proof.md or in the research the brief cites."""
    allowed = set(_NUMBER.findall(proof))
    for text in research:
        allowed |= set(_NUMBER.findall(text))
    problems = []
    for where, text in _texts(brief):
        for match in _RESULT.finditer(text):
            if _TIMING_BEFORE.search(text[: match.start()]) and "hour" in match.group(0).lower():
                continue
            numbers = _NUMBER.findall(match.group(0))
            if not all(number in allowed for number in numbers):
                problems.append(
                    f'{where}: "{match.group(0).strip()}" reads as a result; cite results only '
                    "from brand/proof.md (or a stat with its research source), otherwise "
                    "describe a concrete scenario"
                )
    return problems
