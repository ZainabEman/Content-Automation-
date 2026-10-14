"""Social copy from the formulas into the package's brief.json (Phase 6 P6-D8, C6-5).

A saved social_graphic, carousel or facebook_ad script fills only the fields of its own
deliverable, so build, the overlay and post.md read them as before:
- social_graphic: headline -> post.headline; copy -> captions.<deliverable> (line 1 the hook,
  then 3-5 takeaway lines, the last line the question ending in "?");
- facebook_ad: primary_text -> ad.primaryText, headline -> ad.headline, description ->
  ad.subheadline, cta -> ad.cta;
- carousel: slide_NN -> carousel.slides[N].headline (line 1) and .body (the other lines), when
  brief.json has the same number of slides.
Copy that does not fit a field is kept in the script and named in a warning; a package without
brief.json is left alone. Packages without a script build and render unchanged.
"""

import json
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
    lines = _lines(text)
    if len(lines) < 2 + MIN_TAKEAWAYS or not lines[-1].endswith("?"):
        return None
    takeaways = lines[1:-1]
    if len(takeaways) > MAX_TAKEAWAYS:
        return None
    return {"hook": lines[0], "takeaways": takeaways, "question": lines[-1]}


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
            slot["headline"] = texts["headline"]
            applied.append("post.headline")
        caption = _caption(texts["copy"])
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
