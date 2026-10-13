import json
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from content_automation.registry import open_registry
from content_automation.registry.items import Item, create_item


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp registry location; the working folder is the temp folder, so no real .env."""
    monkeypatch.chdir(tmp_path)
    return tmp_path / "state" / "registry.db"


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config" / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"next_id": 1}), encoding="utf-8")
    return path


@pytest.fixture
def registry(db_path: Path, config_path: Path) -> Iterator[sqlite3.Connection]:
    conn = open_registry(db_path, config_path)
    yield conn
    conn.close()


@pytest.fixture
def new_item(registry: sqlite3.Connection) -> Callable[..., Item]:
    def factory(**fields: Any) -> Item:
        values: dict[str, Any] = {
            "kind": "post", "title": "AI chatbots for dentists",
            "topic": "AI chatbots for dentists", "platforms": ["linkedin"],
        }
        values.update(fields)
        return create_item(registry, **values)

    return factory
