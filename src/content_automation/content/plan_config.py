"""The calendar v2 `plan` block of config/calendar.json (Phase 5 P5-D12, C5-4, C5-5, C5-14).

calendar.json keeps its weekly `slots` (`ca calendar new`, unchanged) and may add `plan`:
- types: plan-only content types (youtube_longform, podcast_episode, youtube_short, ...) with
  their platform and registry kind; `parent` makes a type derived (a short is planned only from
  its parent video, `bufferDays` after it); `enabled: false` keeps a type out of new plans;
- slots: per weekday, the types one idea fills (one row per platform, C5-13); `everyWeeks`
  for schedules such as a podcast every second week (even ISO weeks);
- targets: posts per day and per-week counts that `ca calendar plan` reports against;
- pillarTolerance: how far a pillar's share may drift from config/strategy.json.
"""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError

from content_automation.content.deliverables import DeliverableCatalog, ItemKind
from content_automation.core.files import CamelModel

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
NOT_PRODUCIBLE = "not producible until Phase 8/9"


class PlanConfigError(ValueError):
    """An invalid plan block in config/calendar.json."""


class _Model(CamelModel):
    model_config = ConfigDict(extra="forbid")


class PlanType(_Model):
    platform: str = Field(min_length=1)
    kind: ItemKind
    parent: str | None = None  # derived: planned only from a row of this type
    buffer_days: int = Field(default=0, ge=0)
    enabled: bool = True
    note: str | None = Field(default=None, alias="_note")


class PlanSlot(_Model):
    weekday: Weekday
    types: list[str] = Field(min_length=1)
    every_weeks: int = Field(default=1, ge=1)


class Targets(_Model):
    post_types: list[str] = Field(default_factory=list)
    posts_per_day_min: int = Field(default=0, ge=0)
    posts_per_day_max: int = Field(default=99, ge=0)
    per_week: dict[str, int] = Field(default_factory=dict)


class Plan(_Model):
    note: str | None = Field(default=None, alias="_note")
    types: dict[str, PlanType] = Field(default_factory=dict)
    slots: list[PlanSlot] = Field(min_length=1)
    targets: Targets = Field(default_factory=Targets)
    pillar_tolerance: float = Field(default=0.15, ge=0, le=1)

    def platform_of(self, content_type: str, catalog: DeliverableCatalog) -> str:
        spec = catalog.deliverables.get(content_type)
        if spec is not None:
            return spec.platform or ""
        return self.types[content_type].platform

    def kind_of(self, content_type: str, catalog: DeliverableCatalog) -> ItemKind:
        spec = catalog.deliverables.get(content_type)
        return spec.item_kind if spec is not None else self.types[content_type].kind

    def enabled(self, content_type: str) -> bool:
        found = self.types.get(content_type)
        return found is None or found.enabled

    def derived_from(self, content_type: str) -> list[str]:
        return [key for key, spec in self.types.items()
                if spec.parent == content_type and spec.enabled]


def _raw(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_plan(path: Path, catalog: DeliverableCatalog) -> Plan | None:
    """The plan block (None when calendar.json has none: only the weekly flow)."""
    block = _raw(path).get("plan")
    if block is None:
        return None
    try:
        plan = Plan.model_validate(block)
    except ValidationError as error:
        fields = sorted({".".join(str(p) for p in issue["loc"]) for issue in error.errors()})
        raise PlanConfigError(f"{path.name} plan is invalid; check: {', '.join(fields)}.") from None
    known = set(catalog.deliverables) | set(plan.types)
    clash = sorted(set(catalog.deliverables) & set(plan.types))
    unknown = sorted({t for slot in plan.slots for t in slot.types} - known)
    unknown += sorted({spec.parent for spec in plan.types.values() if spec.parent} - known)
    if clash or unknown:
        raise PlanConfigError(
            f"{path.name} plan: "
            + "; ".join(([f"types already in deliverables.json: {', '.join(clash)}"] if clash
                         else []) + ([f"unknown types: {', '.join(unknown)}"] if unknown else []))
        )
    return plan


def plan_only_types(path: Path) -> dict[str, str]:
    """Plan-only content type -> platform (C5-5): accepted by `calendar check`, skipped by
    `calendar generate`. Empty when there is no (valid) plan block."""
    types = _raw(path).get("plan", {}).get("types", {})
    if not isinstance(types, dict):
        return {}
    return {key: str(spec.get("platform", "")) for key, spec in types.items()
            if isinstance(spec, dict)}
