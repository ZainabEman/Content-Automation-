"""Content checks on brief.json: a real hook, distinct tips with a how, a CTA that works on
the platform, and no result numbers except those in docs/company/proof.md or the research."""

import re
from collections.abc import Iterable

from content_automation.content.brief import ContentBrief, ImageSlot
from content_automation.workflows.design_system import DesignSystem

SAME_POINT = 0.6  # tips whose key words overlap this much make the same point
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


def _key_words(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if word not in _STOP}


def _overlap(first: set[str], second: set[str]) -> float:
    return len(first & second) / len(first | second) if first and second else 0.0


def _carousels(brief: ContentBrief) -> Iterable[tuple[str, ImageSlot]]:
    for name in ("carousel", "post"):
        slot: ImageSlot | None = getattr(brief, name)
        if slot is not None and slot.format == "carousel" and slot.slides:
            yield name, slot


def carousel_problems(
    brief: ContentBrief, system: DesignSystem, platforms: dict[str, str] | None = None
) -> list[str]:
    """platforms: the platform of each brief part (from its deliverable); default the brief's."""
    platforms = platforms or {}
    problems = []
    for name, slot in _carousels(brief):
        hook, tips, last = slot.slides[0], slot.slides[1:-1], slot.slides[-1]
        if not slot.audience_line:
            problems.append(
                f'{name}.audienceLine: the hook names the audience, e.g. "FOR DENTAL PRACTICES"'
            )
        if hook.visual or hook.chat or hook.diagram or _TIP_LIKE.match(hook.headline):
            problems.append(
                f"{name}.slides[1] is the hook: it names the problem or the promise and carries "
                "no tip (no tip text, visual, chat or diagram)"
            )
        for number, tip in enumerate(tips, start=2):
            if not (tip.subheadline or tip.chat or tip.diagram):
                problems.append(
                    f"{name}.slides[{number}]: give the concrete how or an example in "
                    "subheadline, or show it with a chat or diagram"
                )
        words = [_key_words(f"{tip.headline} {tip.subheadline or ''}") for tip in tips]
        for first in range(len(tips)):
            for second in range(first + 1, len(tips)):
                if _overlap(words[first], words[second]) >= SAME_POINT:
                    problems.append(
                        f"{name}.slides[{first + 2}] and slides[{second + 2}] make the same "
                        "point: give each tip its own idea"
                    )
        rule = system.cta_rules.get(platforms.get(name, brief.platform))
        cta = (last.cta or "").lower()
        fits = rule is None or not cta or (
            not any(word in cta for word in rule.avoid)
            and any(re.search(rf"\b{re.escape(word)}\b", cta) for word in rule.require)
        )
        if rule is not None and not fits:
            problems.append(f'{name}.slides[{len(slot.slides)}].cta "{last.cta}": {rule.use}')
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
        for index, step in enumerate(slot.steps, start=1):
            yield f"{name}.steps[{index}]", step
        for number, slide in enumerate(slot.slides, start=1):
            for field, value in (("headline", slide.headline), ("subheadline", slide.subheadline),
                                 ("cta", slide.cta)):
                if value:
                    yield f"{name}.slides[{number}].{field}", value
            for bubble in slide.chat:
                yield f"{name}.slides[{number}].chat", bubble.text
            for step in slide.diagram:
                yield f"{name}.slides[{number}].diagram", step
    for key, caption in brief.captions.items():
        for value in (caption.hook, *caption.lines, caption.question):
            yield f"captions.{key}", value
    if brief.caption is not None:
        for value in (brief.caption.hook, *brief.caption.lines, brief.caption.question):
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
            numbers = _NUMBER.findall(match.group(0))
            if not all(number in allowed for number in numbers):
                problems.append(
                    f'{where}: "{match.group(0).strip()}" reads as a result; cite results only '
                    "from docs/company/proof.md (or a stat with its research source), otherwise "
                    "describe a concrete scenario"
                )
    return problems
