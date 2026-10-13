import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from content_automation.registry import open_registry
from content_automation.registry.db import RegistryError, transaction
from content_automation.registry.ids import (
    UnknownItem,
    allocate_id,
    format_id,
    load_config,
    parse_id,
    peek_next_id,
    resolve,
)
from content_automation.registry.items import AliasTaken, Item, add_alias, aliases, get_item


def test_format_and_parse() -> None:
    assert [format_id(n) for n in (1, 7, 24, 999, 1000)] == [
        "BG-001", "BG-007", "BG-024", "BG-999", "BG-1000"
    ]
    assert [parse_id(t) for t in ("BG-024", "bg-24", " BG24 ", "BG-1000")] == [24, 24, 24, 1000]
    assert [parse_id(t) for t in ("BG-0", "2026-W42-03", "BG-", "XBG-1")] == [None] * 4


def test_ids_are_sequential(new_item: Callable[..., Item]) -> None:
    assert [new_item(title=f"Topic {n}").id for n in range(3)] == ["BG-001", "BG-002", "BG-003"]


def test_ids_are_never_reused_after_delete(new_item: Callable[..., Item],
                                           registry: sqlite3.Connection) -> None:
    first, second = new_item(title="One"), new_item(title="Two")
    with transaction(registry):  # a hard delete (no API offers one): the number stays used
        for table in ("publications", "versions", "aliases"):
            registry.execute(f"DELETE FROM {table} WHERE item_id = ?", (second.id,))
        registry.execute("DELETE FROM items WHERE id = ?", (second.id,))
    assert first.id == "BG-001"
    assert new_item(title="Three").id == "BG-003"


def test_rolled_back_allocation_is_not_consumed(registry: sqlite3.Connection) -> None:
    with pytest.raises(RuntimeError), transaction(registry):
        allocate_id(registry)
        raise RuntimeError("stop")
    assert allocate_id(registry) == "BG-001"


def test_config_sets_the_start_and_only_raises_it(db_path: Path, config_path: Path) -> None:
    config_path.write_text(json.dumps({"next_id": 24}), encoding="utf-8")
    conn = open_registry(db_path, config_path)
    assert allocate_id(conn) == "BG-024"
    conn.close()
    config_path.write_text(json.dumps({"next_id": 5}), encoding="utf-8")
    conn = open_registry(db_path, config_path)
    assert peek_next_id(conn) == "BG-025"  # lowering next_id never brings an ID back
    conn.close()
    config_path.write_text(json.dumps({"next_id": 1000}), encoding="utf-8")
    conn = open_registry(db_path, config_path)
    assert allocate_id(conn) == "BG-1000"
    conn.close()


@pytest.mark.parametrize("text", ['{"next_id": 0}', '{"next_id": "7"}', '{"next_id": true}',
                                  "not json"])
def test_bad_config_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "registry.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RegistryError):
        load_config(path)


def test_alias_resolution(new_item: Callable[..., Item], registry: sqlite3.Connection) -> None:
    item = new_item()
    add_alias(registry, item.id, "2026-W42-03")
    add_alias(registry, "2026-w42-03", "2026-10-03_ai-chatbots-for-dentists")
    add_alias(registry, item.id, "2026-W42-03")  # already there: no-op
    for ref in ("BG-001", "bg-1", "2026-W42-03", "2026-w42-03",
                " 2026-10-03_ai-chatbots-for-dentists "):
        assert resolve(registry, ref) == item.id
    assert get_item(registry, "2026-W42-03") == get_item(registry, item.id)
    assert aliases(registry, item.id) == ["2026-W42-03", "2026-10-03_ai-chatbots-for-dentists"]


def test_alias_errors(new_item: Callable[..., Item], registry: sqlite3.Connection) -> None:
    first, second = new_item(title="One"), new_item(title="Two")
    add_alias(registry, first.id, "2026-W42-01")
    with pytest.raises(AliasTaken, match="already names BG-001"):
        add_alias(registry, second.id, "2026-W42-01")
    with pytest.raises(RegistryError, match="looks like a BG ID"):
        add_alias(registry, second.id, "BG-9")
    with pytest.raises(UnknownItem, match="BG-007 does not exist"):
        resolve(registry, "BG-7")
    with pytest.raises(UnknownItem, match="nothing-here"):
        resolve(registry, "nothing-here")
