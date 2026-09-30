"""App code may reach a provider adapter only through its capability entry package."""

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "content_automation"
AI_PREFIX = "content_automation.ai."


def _module_name(path: Path, root: Path) -> str:
    parts = path.relative_to(root.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imported_modules(path: Path, root: Path) -> list[str]:
    module = _module_name(path, root)
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            names.append(target)
            names.extend(f"{target}.{alias.name}" for alias in node.names)
    return names


def _violations(root: Path = PACKAGE_ROOT) -> list[str]:
    problems = []
    for path in root.rglob("*.py"):
        importer = _module_name(path, root)
        for imported in _imported_modules(path, root):
            if not imported.startswith(AI_PREFIX) or ".providers" not in imported:
                continue
            capability = imported.removeprefix(AI_PREFIX).split(".", 1)[0]
            allowed = f"{AI_PREFIX}{capability}"
            if importer != allowed and not importer.startswith(f"{allowed}."):
                problems.append(f"{path.relative_to(root)} imports {imported}")
    return problems


def test_only_capability_packages_import_their_providers() -> None:
    assert _violations() == []


def test_boundary_check_detects_violations(tmp_path: Path) -> None:
    root = tmp_path / "content_automation"
    files = {
        "workflows/bad.py": "from content_automation.ai.image.providers import mock\n",
        "ai/voice/bad.py": "import content_automation.ai.image.providers.mock\n",
        "ai/image/ok.py": "from .providers import mock\n",
        "ai/image/providers/ok.py": "from content_automation.ai.image import ImageRequest\n",
    }
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")

    problems = _violations(root)

    offenders = {Path(problem.split(" imports ")[0]).as_posix() for problem in problems}
    assert offenders == {"workflows/bad.py", "ai/voice/bad.py"}
