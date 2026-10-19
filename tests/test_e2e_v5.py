"""scripts/e2e_v5.py: the PRD v5 §7 criteria that run offline, on mocks, in a temp folder."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "e2e_v5.py"


def test_v5_end_to_end() -> None:
    spec = importlib.util.spec_from_file_location("e2e_v5", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results = module.run()
    failed = [f"{text}: {note}" for text, passed, note in results if not passed]
    assert len(results) == 9 and failed == []
