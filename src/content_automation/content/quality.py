"""Content checks on brief.json, run by the dry run (nothing is made while one fails).

- Carousel story: hook -> problem -> steps or insights -> example or result -> cta, 6-8 slides.
- Animated carousel (slides with a type): cover -> point/stat/list -> final question, the
  writer limits of config/carousel_design.json, and big numbers only from the cited research.
- Middle slides teach something usable today: specific, never generic, and the step, insight
  and example slides show the automation concretely (a channel or tool and a timing).
- Posts: the supporting line and the key points are specific too.
- Insights: at least 6 specific findings from the research, each with its source; their
  numbers must be in the article they cite.
- Captions: 120-200 words, 3-5 takeaways, a question, the CTA with the offer.
- Numbers that read as results come only from docs/company/proof.md or the cited research.
"""

import re
from collections.abc import Iterable

from content_automation.content.brief import (
    MIN_INSIGHTS,
    Caption,
    ContentBrief,
    ImageSlot,
    SlideSlot,
    is_animated,
)
from content_automation.workflows.carousel_design import CarouselDesign, slide_problems
from content_automation.workflows.design_system import DesignSystem

SAME_POINT = 0.6  # tips whose key words overlap this much make the same point
CAPTION_MIN_WORDS, CAPTION_MAX_WORDS = 120, 200
CAPTION_MAX_WORDS_BY_PLATFORM = {"linkedin": 250}  # LinkedIn shows longer professional text
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "for", "from", "get", "how", "in",
    "into", "is", "it", "its", "more", "of", "on", "or", "our", "so", "than", "that", "the",
    "their", "them", "they", "this", "to", "up", "use", "with", "you", "your",
})
_TIP_LIKE = re.compile(r"^\s*(?:tip|step)\s*\d|^\s*\d+\s*[.)]", re.IGNORECASE)
# Numbers that read as results: percentages, multiples, money, counts of business outcomes.
_RESULT = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|percent\b|x\b|×|times\b)"
    r"|[€$£]\s*\d+(?:[.,]\d+)*|\d+(?:[.,]\d+)*\s*(?:€|eur\b|euros?\b|dollars?\b)"
    r"|\d+(?:[.,]\d+)*\s+(?:more\s+|new\s+|extra\s+)?(?:leads|clients|customers|sales|bookings|"
    r"appointments|calls|hours|reviews|patients|orders)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# "within 5 minutes", "after 24 hours": a timing, not a result
_TIMING_BEFORE = re.compile(r"(?:within|after|before|every|each|per|next|first|in the first)\s+$",
                            re.IGNORECASE)

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
)
TIMINGS = (  # real times: they make a line specific
    "minute", "minutes", "min", "hour", "hours", "day", "days", "week", "weeks", "month",
    "months", "morning", "evening", "night", "overnight", "same day", "same-day", "24/7",
    "weekend", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "daily", "weekly", "instantly", "immediately", "tomorrow", "today",
)
SEQUENCE = ("within", "after", "before", "every", "once", "when", "until", "then")  # "when" only
# Empty marketing phrases: a line with one of them is generic, whatever else it says.
BUZZWORDS = (
    "game changer", "game-changer", "next level", "unlock", "supercharge", "revolutionize",
    "revolutionise", "seamless", "cutting-edge", "cutting edge", "world-class", "fast-paced",
    "sets the next step", "take your business", "skyrocket", "effortless",
)
_QUOTED = re.compile(r"[\"“”‘’]|'[^']{3,}'")


def _has(text: str, words: Iterable[str]) -> bool:
    low = text.lower()
    return any(re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", low) for word in words)


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
    texts = [slide.headline, slide.subheadline or "", slide.body or "", slide.stat or ""]
    texts += list(slide.items)
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
        if is_animated(slot):
            continue  # animated_carousel_problems
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
                f'"{label}" (from docs/company/services.md)'
            )
    return problems


def animated_carousel_problems(
    brief: ContentBrief, design: CarouselDesign, research: Iterable[str]
) -> list[str]:
    """The animated carousel: every slide has a type, the structure and writer limits of
    carousel_design.json hold, and each big number is written in the cited research."""
    slot = brief.carousel
    if slot is None or not is_animated(slot):
        return []
    untyped = [number for number, slide in enumerate(slot.slides, start=1) if slide.type is None]
    if untyped:
        return [
            f"carousel.slides[{number}].type: set it ({' -> '.join(design.structure)})"
            for number in untyped
        ]
    slides = [slide.text() for slide in slot.slides]
    problems = slide_problems(slides, design)
    allowed = {number for text in research for number in _NUMBER.findall(text)}
    for number, slide in enumerate(slides, start=1):
        figures = _NUMBER.findall(slide.stat or "")
        if any(figure not in allowed for figure in figures):
            problems.append(
                f'carousel.slides[{number}].stat "{slide.stat}": the number must be written in '
                "a research article listed in sourceArticleIds; never invent one"
            )
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
        problems.append(f'cta: name the offer "{label}" (from docs/company/services.md)')
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
        for number, slide in enumerate(slot.slides, start=1):
            for value in _slide_texts(slide) + [slide.cta or ""]:
                if value:
                    yield f"{name}.slides[{number}]", value
    for key, caption in brief.captions.items():
        for value in (caption.hook, *caption.takeaways, caption.question):
            yield f"captions.{key}", value
    if brief.caption is not None:
        for value in (brief.caption.hook, *brief.caption.takeaways, brief.caption.question):
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
                    "from docs/company/proof.md (or a stat with its research source), otherwise "
                    "describe a concrete scenario"
                )
    return problems
