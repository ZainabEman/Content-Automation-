"""Which gate a decision acts on (PRD D5, §14 D-10, D-19, D-22) and the next allowed actions.

Pure checks on an item's statuses; nothing here writes. The idea gate comes first:
- approve: idea proposed, or rejected while generation is not_started/failed/partial (D-10);
  review gate: generation generated and review not_reviewed.
- reject: idea proposed, or approved inside the same window; review gate as for approve.
- revise: idea proposed, or approved inside the window (D-22); review gate: generation
  generated and review not_reviewed or approved (D-19).
"""

from dataclasses import dataclass
from typing import Literal

from content_automation.registry.decisions import Gate
from content_automation.registry.items import Item
from content_automation.registry.statuses import IDEA_WINDOW

Action = Literal["approve", "reject", "revise"]
GATES: tuple[Gate, ...] = ("idea", "review")  # D5: the idea gate first
REVIEW_REVISABLE = ("not_reviewed", "approved")
_IDEA_ALSO: dict[Action, str] = {  # besides proposed, inside the generation window (D-10, D-22)
    "approve": "rejected",
    "reject": "approved",
    "revise": "approved",
}


def gate_open(item: Item, action: Action, gate: Gate) -> bool:
    """Whether `action` may act on `gate` of the item now."""
    if gate == "idea":
        if item.idea_status == "proposed":
            return True
        return (item.idea_status == _IDEA_ALSO[action]
                and item.generation_status in IDEA_WINDOW)
    if item.generation_status != "generated":
        return False
    if action == "revise":
        return item.review_status in REVIEW_REVISABLE
    return item.review_status == "not_reviewed"


def open_gate(item: Item, action: Action) -> Gate | None:
    """The gate `action` acts on when the user names none, or None if none is open."""
    return next((gate for gate in GATES if gate_open(item, action, gate)), None)


def closed_message(item: Item, action: Action, gate: Gate | None) -> str:
    """Why `action` cannot act now, with the hint that fits the item's statuses."""
    where = f"the {gate} gate is not open" if gate else f"there is nothing to {action}"
    state = (f"idea is {item.idea_status}, generation is {item.generation_status}, review is "
             f"{item.review_status}")
    if item.idea_status == "revision_requested":
        hint = f' It waits for: ca item resubmit {item.id} --title "<new topic>".'
    elif item.review_status == "rejected":
        hint = " Review rejected is final."
    elif item.review_status == "changes_requested":
        hint = (f" Changes are already requested; v{item.current_version} waits for "
                "generation.")
    elif item.generation_status in ("queued", "running"):
        hint = " Generation is in progress; wait for it to finish."
    elif item.generation_status == "generated" and item.review_status == "approved":
        hint = " The review is approved; revise it to ask for changes."
    else:
        hint = ""
    return f"{item.id}: {where} ({state}).{hint}"


@dataclass(frozen=True)
class NextAction:
    action: str  # approve, reject, revise, resubmit, generate, wait
    gate: str | None
    hint: str


def next_actions(item: Item) -> list[NextAction]:
    """What the user can do with the item now (for `ca item status`)."""
    actions: list[NextAction] = []
    for action in ("approve", "reject", "revise"):
        gate = open_gate(item, action)
        if gate is None:
            continue
        example = {
            "approve": f"ca item approve {item.id}",
            "reject": f'ca item reject {item.id} "<reason>"',
            "revise": (f'ca item revise {item.id} "<feedback>"'
                       + (' --title "<new topic>"' if gate == "idea" else "")),
        }[action]
        actions.append(NextAction(action, gate, example))
    if item.idea_status == "revision_requested":
        actions.append(NextAction("resubmit", "idea",
                                  f'ca item resubmit {item.id} --title "<new topic>"'))
    if item.idea_status == "approved" and item.generation_status in IDEA_WINDOW:
        actions.append(NextAction("generate", None,
                                  '"generate approved" (calendar) or the make-content build'))
    if item.generation_status in ("queued", "running"):
        actions.append(NextAction("wait", None, "generation is in progress (ca jobs list)"))
    return actions
