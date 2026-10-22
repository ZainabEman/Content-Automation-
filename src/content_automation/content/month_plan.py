"""`ca plan month YYYY-MM` (PRD v5 R7): the monthly social plan at about 2 graphics a day.

The count is graphicsPerDay x the days of the month, kept within 30-60 (a carousel is one
asset); the category mix of config/deliverables.json monthlyPlan is scaled to it (largest
remainder). Days are filled two at a time with the categories that are furthest behind their
share, never the same category twice a day and, while another is left, not the category of the
day before, so formats spread over the month. Every romanEvery-th LinkedIn/Facebook post or ad
is planned with requires_roman (a founder variant, Higgsfield Soul 2.0).

Topics: approved, unplanned ideas of the backlog (best score first) and the --topic texts. Each
topic goes to the slot whose category fits it best (a verified service fit favours an ad, how-to
and list wording a carousel, news and study wording LinkedIn); topic → service matching is
content/relevance.py, unchanged. Slots without a topic stay open. v6 (R2, R6): a topic needs no
service (service insight-only is a valid plan); the same theme of config/topic_pool.json is not
planned back to back; topics generated, rejected or deleted before (or close rewordings) are
left out by the caller (content/topic_pool.py).

The layout variant of each asset is simulated with the real rotation (content/direction_pick.py)
in date order, so the plan shows it and proves R5.3: no platform gets three consecutive images
with the same variant and background treatment. Each asset carries the German publishing
metadata to write (caption, hashtags within the platform's limits, headline, hook, CTA, alt
text; ads also primary text, headline, description and a Meta CTA button).

Free: the plan and its cost estimate (the dry run of the planned volume) are written to
calendar/<YYYY-MM>-month-plan.json/.csv. `--apply` writes the assets that have an approved idea
into the weekly calendar files as Approved rows (the calendar v2 path: registry items, inherited
approval, Format "roman" for requires_roman); nothing is generated or paid.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from content_automation.ai.image import get_provider
from content_automation.content.deliverables import DeliverableCatalog, MonthlyPlan
from content_automation.content.direction_brief import slide_roles
from content_automation.content.direction_pick import direction_format, pick_direction
from content_automation.content.directions import DirectionCatalog
from content_automation.content.relevance import service_fit
from content_automation.content.routing import illustration_route
from content_automation.content.topic_pool import theme_of
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.references.services import ServiceCatalog

ROMAN_FORMAT = "roman"  # the calendar's Format value for a requires_roman row
# R7.4 + the existing platform limits (config/formulas.json social_graphic: 3-5, #BrandedGenius
# included); 2026-10-22: LinkedIn too 3-5, 3 by default (it was planned with exactly 3)
HASHTAGS = {"linkedin": (3, 5), "facebook": (3, 5), "instagram": (3, 5)}
_HOW_TO = re.compile(r"\b(wie|so |schritte?|tipps?|checkliste|fehler|anzeichen|regeln|"
                     r"how|steps?|tips?|checklist|mistakes?|signs)\b", re.IGNORECASE)
_NEWS = re.compile(r"\b(studie|bericht|umfrage|gesetz|verordnung|ai act|ki-verordnung|bsi|"
                   r"behörde|trend|news|report|study|survey|law)\b", re.IGNORECASE)


class MonthPlanError(ValueError):
    """The month cannot be planned (no mix, an unknown deliverable, a bad label)."""


@dataclass
class Topic:
    title: str
    source: str  # idea:BG-x or topic:<text>
    idea_id: str | None = None
    score: float = 0.0


@dataclass
class Asset:
    number: int
    day: str
    deliverable: str
    category: str
    platform: str
    requires_roman: bool
    variant: str
    treatment: str
    topic: str | None
    source: str | None
    service: str | None
    pictures: int
    estimate_usd: float
    metadata: dict[str, Any] = field(default_factory=dict)
    theme: str | None = None  # v6 R2: the topic pool theme (config/topic_pool.json)


def scale_mix(mix: dict[str, int], total: int) -> dict[str, int]:
    """The mix scaled to `total` assets (largest remainder, ties in config order)."""
    weight = sum(mix.values())
    exact = {key: value * total / weight for key, value in mix.items()}
    counts = {key: int(value) for key, value in exact.items()}
    rest = sorted(mix, key=lambda key: -(exact[key] - counts[key]))
    for key in rest[:total - sum(counts.values())]:
        counts[key] += 1
    return counts


def month_total(config: MonthlyPlan, days: int) -> int:
    return max(config.min_per_month, min(config.max_per_month, config.graphics_per_day * days))


def day_quotas(total: int, days: int, per_day: int) -> list[int]:
    """How many assets each day gets: per_day, fewer on evenly spread days when total is
    lower."""
    quotas = [per_day] * days
    spare = per_day * days - total
    for index in range(spare):
        quotas[(index * days) // max(1, spare)] -= 1
    return quotas


def schedule(counts: dict[str, int], quotas: list[int]) -> list[list[str]]:
    """Deliverables per day: the furthest behind its share first, never twice a day, and not
    the category of the day before while another is left."""
    left = dict(counts)
    total = {key: max(1, value) for key, value in counts.items()}
    days: list[list[str]] = []
    previous: set[str] = set()
    for quota in quotas:
        today: list[str] = []
        for _ in range(quota):
            options = [key for key in left if left[key] > 0 and key not in today]
            if not options:
                break
            fresh = [key for key in options if key not in previous] or options
            best = max(fresh, key=lambda key: (left[key] / total[key], left[key]))
            today.append(best)
            left[best] -= 1
        days.append(today)
        previous = set(today)
    return days


def _affinity(topic: Topic, deliverable: str, services: ServiceCatalog | None) -> float:
    score = 0.0
    verified = services is not None and service_fit([topic.title], services).service_id
    if deliverable == "facebook_ad":
        score += 2.0 if verified else -2.0
    if deliverable == "instagram_carousel" and _HOW_TO.search(topic.title):
        score += 1.0
    if deliverable == "linkedin_post" and _NEWS.search(topic.title):
        score += 1.0
    return score + topic.score / 100


def _service(topic: Topic | None, services: ServiceCatalog | None) -> str | None:
    if topic is None or services is None:
        return None
    return service_fit([topic.title], services).label


def metadata_template(deliverable: str, platform: str, roman: bool) -> dict[str, Any]:
    """The German publishing metadata each asset gets (R7.4), filled by the writer later."""
    low, high = HASHTAGS.get(platform, (3, 5))
    meta: dict[str, Any] = {
        "language": "de",
        "headline": "<German headline on the image>",
        "hook": "<German hook: line 1 of the caption>",
        "caption": "<German caption: hook, takeaways, one question, the CTA>",
        "hashtags": f"<{low}-{high} hashtags incl. #BrandedGenius, {low} by default>"
                    if low != high else
                    f"<exactly {low} hashtags incl. #BrandedGenius>",
        "cta": "<German call to action>",
        "altText": "<German alt text>",
    }
    if deliverable == "instagram_carousel":
        meta["altText"] = "<German alt text per slide>"
    if deliverable == "facebook_ad":
        meta["adFields"] = {"primaryText": "<German primary text>",
                            "headline": "<German headline below the image>",
                            "description": "<optional German description>",
                            "ctaButton": "<one of config/meta_cta.json>"}
    if roman:
        meta["aiDisclosure"] = "KI-generiertes Bild (Roman, erstellt mit einem KI-Modell)"
    return meta


def _cost(settings: Settings, provider: str, pictures: int) -> float:
    try:
        caps = get_provider(provider, settings.model_copy(
            update={"image_provider": provider})).capabilities
    except Exception:  # noqa: BLE001 - an estimate must never stop the free plan
        return 0.0
    per_image = caps.est_cost_usd_per_image.get(settings.image_design_size, 0.0)
    return round(per_image * pictures + caps.est_cost_usd_per_request, 4)


def plan_month(settings: Settings, deliverables: DeliverableCatalog, catalog: DirectionCatalog,
               label: str, days: list[date], topics: list[Topic],
               services: ServiceCatalog | None = None,
               history: dict[tuple[str, str], list[str]] | None = None) -> list[Asset]:
    """The month's assets in date order (free; nothing is written or called)."""
    config = deliverables.monthly_plan
    if config is None:
        raise MonthPlanError("config/deliverables.json has no monthlyPlan (PRD R7.3)")
    total = month_total(config, len(days))
    counts = scale_mix(config.mix, total)
    plan = schedule(counts, day_quotas(total, len(days), config.graphics_per_day))
    pool = list(topics)
    recent: dict[tuple[str, str], list[str]] = {key: list(value)
                                                for key, value in (history or {}).items()}
    assets: list[Asset] = []
    roman_count = 0
    last_theme: str | None = None
    for day, names in zip(days, plan, strict=True):
        for name in names:
            spec = deliverables.deliverables[name]
            platform = spec.platform or ""
            format_name = direction_format(spec.part, platform)
            if format_name is None:
                raise MonthPlanError(f"{name} takes no layout variant (monthlyPlan.mix)")
            roman = False
            if name in config.roman_deliverables and config.roman_every:
                roman_count += 1
                roman = roman_count % config.roman_every == 0
            key = (format_name, platform)
            chosen, _ = pick_direction(catalog, format_name, platform,
                                       seed=f"{label}-{len(assets) + 1}",
                                       recent=recent.get(key, [])[:2], roman_ok=True,
                                       roman=roman)
            recent[key] = [chosen.id, *recent.get(key, [])][:5]
            choices = [item for item in pool
                       if last_theme is None or theme_of(item.title) != last_theme] or pool
            topic = (max(choices, key=lambda item: _affinity(item, name, services))
                     if choices else None)
            theme = theme_of(topic.title) if topic is not None else None
            if topic is not None:
                pool.remove(topic)
                last_theme = theme
            pictures = len(slide_roles(chosen)) if chosen.format == "carousel" else 1
            provider = chosen.provider if chosen.roman else illustration_route(settings)
            assets.append(Asset(
                number=len(assets) + 1, day=day.isoformat(), deliverable=name,
                category=chosen.category, platform=platform, requires_roman=chosen.roman,
                variant=chosen.id, treatment=chosen.treatment,
                topic=topic.title if topic else None, source=topic.source if topic else None,
                service=_service(topic, services), pictures=pictures,
                estimate_usd=_cost(settings, provider, pictures),
                metadata=metadata_template(name, platform, chosen.roman), theme=theme))
    return assets


def three_in_a_row(assets: list[Asset]) -> list[str]:
    """R5.3: every platform run of 3 consecutive images with the same variant + treatment."""
    found: list[str] = []
    by_platform: dict[str, list[Asset]] = {}
    for asset in assets:
        by_platform.setdefault(asset.platform, []).append(asset)
    for platform, items in by_platform.items():
        for first, second, third in zip(items, items[1:], items[2:], strict=False):
            if {(a.variant, a.treatment) for a in (first, second, third)} == {
                    (first.variant, first.treatment)}:
                found.append(f"{platform}: {first.variant} {first.treatment} on {first.day}, "
                             f"{second.day}, {third.day}")
    return found


def summary_lines(label: str, assets: list[Asset], days: int) -> list[str]:
    by_category: dict[str, int] = {}
    for asset in assets:
        by_category[asset.category] = by_category.get(asset.category, 0) + 1
    cost = sum(asset.estimate_usd for asset in assets)
    pictures = sum(asset.pictures for asset in assets)
    open_topics = sum(asset.topic is None for asset in assets)
    roman = sum(asset.requires_roman for asset in assets)
    lines = [
        f"Month plan {label}: {len(assets)} graphics over {days} days (a carousel counts as one): "
        + ", ".join(f"{name} {count}" for name, count in by_category.items()) + ".",
        f"Roman (requires_roman, Higgsfield Soul 2.0 via Codex): {roman}; topics open: "
        f"{open_topics}.",
        f"Dry run of the planned volume (estimate, nothing called): {pictures} pictures, about "
        f"${cost:.2f} (OpenRouter designer images and Higgsfield Roman images, an estimate; "
        "text, logo and "
        "website are drawn by the app for free). Each build still has its own dry run and "
        "needs its own \"ok\".",
    ]
    rows = three_in_a_row(assets)
    lines.append("Rotation: no platform has three near-identical images in a row." if not rows
                 else "Rotation problem: " + "; ".join(rows))
    return lines


def write_plan(settings: Settings, label: str, assets: list[Asset]) -> tuple[Path, Path]:
    folder = settings.calendar_dir
    folder.mkdir(parents=True, exist_ok=True)
    data = {"month": label, "assets": [asdict(asset) for asset in assets]}
    target = folder / f"{label}-month-plan.json"
    atomic_write_text(target, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["#", "Planned date", "Deliverable", "Category", "Platform", "Variant",
                     "Treatment", "Requires Roman", "Topic", "Source", "Service fit",
                     "Pictures", "Estimate USD"])
    for asset in assets:
        writer.writerow([asset.number, asset.day, asset.deliverable, asset.category,
                         asset.platform, asset.variant, asset.treatment,
                         "yes" if asset.requires_roman else "no", asset.topic or "(open)",
                         asset.source or "", asset.service or "", asset.pictures,
                         f"{asset.estimate_usd:.3f}"])
    table = folder / f"{label}-month-plan.csv"
    atomic_write_text(table, buffer.getvalue())
    return target, table


__all__ = ["Asset", "MonthPlanError", "Topic", "day_quotas", "metadata_template",
           "month_total", "plan_month", "scale_mix", "schedule", "summary_lines",
           "three_in_a_row", "write_plan"]


def apply_plan(settings: Settings, deliverables: DeliverableCatalog, assets: list[Asset],
               command: str | None) -> tuple[list[Path], list[str]]:
    """--apply: the assets with an approved idea become Approved rows of the weekly calendars
    (calendar v2: registry items with inherited approval); requires_roman rows get Format
    "roman". Rows the week already has (same date and deliverable) are kept; nothing is
    generated."""
    from content_automation.content.calendar import (
        CalendarError,
        calendar_path,
        check_edits,
        read_calendar,
        write_calendar,
    )
    from content_automation.content.plan import week_of
    from content_automation.registry import runtime
    from content_automation.registry.db import transaction
    from content_automation.registry.link import plan_item

    scope = runtime.current()
    if scope is None:
        raise CalendarError("plan month --apply needs the registry.")
    weeks: dict[str, list[dict[str, str]]] = {}
    added: list[str] = []
    skipped: list[str] = []
    with transaction(scope.conn):
        for asset in assets:
            if asset.source is None or not asset.source.startswith("idea:"):
                skipped.append(f"#{asset.number} {asset.day} {asset.deliverable}")
                continue
            week = week_of(date.fromisoformat(asset.day))
            if week not in weeks:
                path = calendar_path(settings, week)
                if path.exists():
                    check_edits(path)
                weeks[week] = [dict(row) for row in read_calendar(path)] if path.exists() else []
            rows = weeks[week]
            if any(row["Planned date"] == asset.day and row["Content type"] == asset.deliverable
                   for row in rows):
                continue
            number = max((int(row["Row"]) for row in rows if row["Row"].isdigit()), default=0)
            spec = deliverables.deliverables[asset.deliverable]
            row = {"Row": str(number + 1), "BG ID": "", "Planned date": asset.day,
                   "Topic": asset.topic or "", "Research source": asset.source,
                   "Platform": asset.platform, "Content type": asset.deliverable,
                   "Status": "Approved", "Version": "", "Package": "",
                   "Content ID": f"{week}-{number + 1:02d}",
                   "Format": ROMAN_FORMAT if asset.requires_roman else ""}
            idea_id = asset.source.removeprefix("idea:")
            item = plan_item(scope.conn, row, week, kind=spec.kind or "post",
                             platform=asset.platform,
                             parent_id=idea_id, idea_id=idea_id, command=command)
            row["BG ID"] = item.id
            rows.append(row)
            added.append(item.id)
    paths = []
    for week, rows in weeks.items():
        if rows:
            write_calendar(calendar_path(settings, week), rows)
            paths.append(calendar_path(settings, week))
    lines = [f"Applied: {len(added)} row(s) into {len(paths)} week file(s), Approved "
             "(inherited from their ideas). Nothing generated."]
    if skipped:
        lines.append(f"Not applied ({len(skipped)}, no approved idea): "
                     + ", ".join(skipped[:8]) + (" …" if len(skipped) > 8 else "")
                     + ". Add and approve ideas (research-ideas), then apply again.")
    return paths, lines
