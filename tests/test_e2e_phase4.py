"""scripts/e2e_phase4.py: PRD Phase 4 §10 criteria 1-9 offline, on mocks, in a temp folder."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "e2e_phase4.py"


def test_phase4_end_to_end() -> None:
    spec = importlib.util.spec_from_file_location("e2e_phase4", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results = module.run()
    failed = [criterion.line() for criterion in results if not criterion.passed]
    assert len(results) == 9 and failed == []
