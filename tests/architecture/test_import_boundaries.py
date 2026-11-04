"""Executable source-dependency rules for Clean Architecture."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src" / "stock_predictor"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.add(node.module)
    return result


def _module_files(relative: str) -> tuple[Path, ...]:
    return tuple((SOURCE_ROOT / relative).rglob("*.py"))


def _assert_no_prefixes(paths: tuple[Path, ...], forbidden: tuple[str, ...]) -> None:
    violations: list[str] = []
    for path in paths:
        for imported in _imports(path):
            if imported.startswith(forbidden):
                violations.append(f"{path.relative_to(PROJECT_ROOT)} imports {imported}")
    assert not violations, "Architecture boundary violations:\n" + "\n".join(violations)


def test_domain_depends_only_on_domain_and_standard_library() -> None:
    _assert_no_prefixes(
        _module_files("domain"),
        (
            "pydantic",
            "pandas",
            "exchange_calendars",
            "stock_predictor.adapters",
            "stock_predictor.application",
            "stock_predictor.bootstrap",
            "stock_predictor.ports",
        ),
    )


def test_ports_do_not_depend_on_application_or_infrastructure() -> None:
    _assert_no_prefixes(
        _module_files("ports"),
        (
            "stock_predictor.adapters",
            "stock_predictor.application",
            "stock_predictor.bootstrap",
        ),
    )


def test_application_does_not_depend_on_adapters_or_bootstrap() -> None:
    _assert_no_prefixes(
        _module_files("application"),
        ("stock_predictor.adapters", "stock_predictor.bootstrap"),
    )
