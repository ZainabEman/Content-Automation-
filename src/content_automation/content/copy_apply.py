"""Social copy from the formulas into the package's brief.json (Phase 6 P6-D8, C6-5).

A saved social_graphic, carousel or facebook_ad script fills only the fields of its own
deliverable, so build, the overlay and post.md read them as before:
- social_graphic: headline -> post.headline; body -> post.subheadline and bullets (3 lines) ->
  post.points (the scene layout's panels); copy -> captions.<deliverable> (line 1 the hook,
  then 3-5 takeaway lines, the last line the question ending in "?");
- facebook_ad: primary_text -> ad.primaryText, headline -> ad.headline, description ->
  ad.subheadline, cta -> ad.cta;
- carousel: slide_NN -> carousel.slides[N].headline (line 1) and .body (the other lines), when
  brief.json has the same number of slides.
Copy that does not fit a field is kept in the script and named in a warning; a package without
brief.json is left alone. Packages without a script build and render unchanged.
"""

import json
import re
from pathlib import Path
from typing import Any

from content_automation.content.brief import MAX_TAKEAWAYS, MIN_TAKEAWAYS
from content_automation.content.package import BRIEF_FILE
from content_automation.content.scripts import Script
from content_automation.core.files import atomic_write_text
from content_automation.registry.items import Item


def _lines(text: str) -> list[str]:
    return [line.strip().lstrip("-•* ").strip() for line in text.splitlines() if line.strip()]


def _caption(text: str) -> dict[str, Any] | None:
    """Hook, takeaways, the question and (live fix) the German line after it; hashtag lines
    at the end are left out (the script keeps the hashtags)."""
    lines = [line for line in _lines(text)
             if not all(word.startswith("#") for word in line.split())]
    asked = [index for index, line in enumerate(lines) if line.endswith("?")]
    if not asked or asked[-1] < 1 + MIN_TAKEAWAYS:
        return None
    question = asked[-1]
    takeaways = lines[1:question]
    if len(takeaways) > MAX_TAKEAWAYS:
        return None
    caption: dict[str, Any] = {"hook": lines[0], "takeaways": takeaways,
                               "question": lines[question]}
    if lines[question + 1:]:
        caption["closingDe"] = " ".join(lines[question + 1:])
    return caption


def apply_copy(item: Item, script: Script) -> tuple[list[str], list[str]]:
    """(the brief.json fields written, warnings)."""
    if not item.package_path:
        return [], []
    path = Path(item.package_path) / BRIEF_FILE
    if not path.is_file():
        return [], [f"{path.as_posix()} not written yet: the copy stays in the script; save "
                    "the script again after brief.json exists"]
    brief: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    texts = {section.key: section.text.strip() for section in script.sections}
    applied: list[str] = []
    warnings: list[str] = []
    deliverable = item.deliverable or ""
    if script.formula == "social_graphic":
        slot = brief.get("post")
        if isinstance(slot, dict):
            marked = re.findall(r"\*([^*]+)\*", texts["headline"])
            slot["headline"] = texts["headline"].replace("*", "")
            if marked:
                slot["highlight"] = marked[:2]
            applied.append("post.headline")
            if texts.get("subtitle"):
                slot["subheadline"] = texts["subtitle"]
                applied.append("post.subheadline")
            if texts.get("bullets"):
                slot["points"] = _lines(texts["bullets"])
                applied.append("post.points")
            card = {name: value for name, value in (
                ("tag", texts.get("tag")), ("subtitle", texts.get("subtitle")),
                ("icons", _lines(texts.get("icons", ""))), ("ctaEn", texts.get("cta_en")),
                ("ctaDe", texts.get("cta_de")), ("stat", texts.get("stat")),
                ("statLabel", texts.get("stat_label"))) if value}
            if card:
                slot["card"] = card
                applied.append("post.card")
        caption = _caption(texts.get("copy", ""))
        if caption is None:
            warnings.append(f"copy kept in the script only: captions.{deliverable} needs the "
                            f"hook line, {MIN_TAKEAWAYS}-{MAX_TAKEAWAYS} takeaway lines and a "
                            "question line ending in ?")
        else:
            brief.setdefault("captions", {})[deliverable] = caption
            applied.append(f"captions.{deliverable}")
    elif script.formula == "facebook_ad":
        slot = brief.get("ad")
        if isinstance(slot, dict):
            slot.update({"primaryText": texts["primary_text"], "headline": texts["headline"],
                         "subheadline": texts["description"], "cta": texts["cta"]})
            applied += ["ad.primaryText", "ad.headline", "ad.subheadline", "ad.cta"]
        else:
            warnings.append("brief.json has no ad: ad copy kept in the script only")
    elif script.formula == "carousel":
        slides = (brief.get("carousel") or {}).get("slides")
        keys = sorted(key for key in texts if key.startswith("slide_"))
        if not isinstance(slides, list) or len(slides) != len(keys):
            warnings.append("brief.json carousel.slides differ from the script's slides: slide "
                            "text kept in the script only")
        else:
            for slide, key in zip(slides, keys, strict=True):
                lines = _lines(texts[key])
                slide["headline"] = lines[0]
                if len(lines) > 1:
                    slide["body"] = " ".join(lines[1:])
            applied.append(f"carousel.slides ({len(keys)})")
    if applied:
        atomic_write_text(path, json.dumps(brief, indent=2, ensure_ascii=False) + "\n")
    return applied, warnings
