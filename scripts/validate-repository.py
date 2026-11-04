#!/usr/bin/env python3
"""Validate repository structure, configuration files, and deployment references."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

_REQUIRED_PATHS = (
    "pyproject.toml",
    "README.md",
    "Dockerfile",
    "compose.yaml",
    "src/stock_predictor/py.typed",
    "deploy/kubernetes/base/kustomization.yaml",
    "infra/terraform/gcp/versions.tf",
    "infra/terraform/azure/versions.tf",
    "docs/operations/setup.md",
    "docs/operations/running.md",
    "docs/operations/debugging.md",
)
_PINNED_ACTION = re.compile(r"^[^\s]+@[0-9a-f]{40}$")
_MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")


class ValidationFailure(RuntimeError):
    """Raised when repository validation detects one or more violations."""


class RepositoryValidator:
    """Deterministic static validation that does not require cloud credentials."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.errors: list[str] = []
        self.checked: list[str] = []

    def run(self) -> None:
        self._required_paths()
        self._toml()
        self._json()
        self._yaml()
        self._python_syntax()
        self._kustomize_references()
        self._workflow_actions()
        self._markdown_links()
        self._terraform_static_policy()
        if self.errors:
            details = "\n".join(f"- {item}" for item in self.errors)
            raise ValidationFailure(f"Repository validation failed:\n{details}")

    def _required_paths(self) -> None:
        for relative in _REQUIRED_PATHS:
            path = self.root / relative
            self.checked.append(relative)
            if not path.exists():
                self.errors.append(f"Required path is missing: {relative}")

    def _toml(self) -> None:
        for path in self.root.rglob("*.toml"):
            if self._ignored(path):
                continue
            self.checked.append(path.relative_to(self.root).as_posix())
            try:
                with path.open("rb") as stream:
                    tomllib.load(stream)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                self.errors.append(f"Invalid TOML {self._relative(path)}: {exc}")

    def _json(self) -> None:
        for path in self.root.rglob("*.json"):
            if self._ignored(path):
                continue
            self.checked.append(self._relative(path))
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.errors.append(f"Invalid JSON {self._relative(path)}: {exc}")

    def _yaml(self) -> None:
        paths = (*self.root.rglob("*.yaml"), *self.root.rglob("*.yml"))
        for path in paths:
            if self._ignored(path):
                continue
            self.checked.append(self._relative(path))
            try:
                tuple(yaml.safe_load_all(path.read_text(encoding="utf-8")))
            except (OSError, yaml.YAMLError) as exc:
                self.errors.append(f"Invalid YAML {self._relative(path)}: {exc}")

    def _python_syntax(self) -> None:
        for base in (self.root / "src", self.root / "tests", self.root / "scripts"):
            if not base.exists():
                continue
            for path in base.rglob("*.py"):
                self.checked.append(self._relative(path))
                try:
                    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                except (OSError, SyntaxError) as exc:
                    self.errors.append(f"Invalid Python {self._relative(path)}: {exc}")

    def _kustomize_references(self) -> None:
        for path in self.root.rglob("kustomization.yaml"):
            if self._ignored(path):
                continue
            payload = self._yaml_mapping(path)
            for key in ("resources", "components", "patchesStrategicMerge"):
                raw = payload.get(key, [])
                if not isinstance(raw, list):
                    self.errors.append(f"{self._relative(path)} {key} must be a list")
                    continue
                for value in raw:
                    if not isinstance(value, str) or value.startswith("http"):
                        continue
                    candidate = (path.parent / value).resolve()
                    if not candidate.exists():
                        self.errors.append(
                            f"Missing Kustomize reference from {self._relative(path)}: {value}"
                        )

    def _workflow_actions(self) -> None:
        workflow_root = self.root / ".github" / "workflows"
        if not workflow_root.exists():
            return
        for path in (*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")):
            payload = self._yaml_mapping(path)
            for action in self._find_values(payload, "uses"):
                if action.startswith("./") or action.startswith("docker://"):
                    continue
                if not _PINNED_ACTION.fullmatch(action):
                    self.errors.append(
                        f"GitHub Action must be pinned to a full commit SHA in "
                        f"{self._relative(path)}: {action}"
                    )

    def _markdown_links(self) -> None:
        for path in self.root.rglob("*.md"):
            if self._ignored(path):
                continue
            text = path.read_text(encoding="utf-8")
            for raw_target in _MARKDOWN_LINK.findall(text):
                target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
                target = target.split("#", maxsplit=1)[0]
                if not target or "://" in target or target.startswith(("mailto:", "#")):
                    continue
                candidate = (path.parent / target).resolve()
                try:
                    candidate.relative_to(self.root)
                except ValueError:
                    self.errors.append(
                        f"Markdown link escapes repository in {self._relative(path)}: {target}"
                    )
                    continue
                if not candidate.exists():
                    self.errors.append(
                        f"Broken Markdown link in {self._relative(path)}: {target}"
                    )

    def _terraform_static_policy(self) -> None:
        for directory in (self.root / "infra" / "terraform").glob("*"):
            if not directory.is_dir():
                continue
            versions = directory / "versions.tf"
            if not versions.is_file():
                self.errors.append(
                    f"Terraform module lacks versions.tf: {self._relative(directory)}"
                )
                continue
            terraform_files = tuple(sorted(directory.glob("*.tf")))
            content = "\n".join(
                item.read_text(encoding="utf-8") for item in terraform_files
            )
            for terraform_file in terraform_files:
                self._terraform_delimiters(terraform_file)
            if "required_version" not in content or "required_providers" not in content:
                self.errors.append(
                    f"Terraform module lacks version constraints: {self._relative(directory)}"
                )
            if re.search(r'(?i)(password|private_key)\s*=\s*"[^$][^"]+"', content):
                self.errors.append(
                    f"Terraform module appears to contain an inline secret: "
                    f"{self._relative(directory)}"
                )

    def _terraform_delimiters(self, path: Path) -> None:
        """Detect unmatched HCL braces while ignoring strings and line comments."""
        text = path.read_text(encoding="utf-8")
        depth = 0
        in_string = False
        escaped = False
        in_line_comment = False
        index = 0
        while index < len(text):
            character = text[index]
            next_character = text[index + 1] if index + 1 < len(text) else ""
            if in_line_comment:
                if character == "\n":
                    in_line_comment = False
                index += 1
                continue
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                index += 1
                continue
            if character == '"':
                in_string = True
            elif character == "#" or (character == "/" and next_character == "/"):
                in_line_comment = True
                if character == "/":
                    index += 1
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth < 0:
                    self.errors.append(
                        f"Unmatched closing brace in Terraform file: {self._relative(path)}"
                    )
                    return
            index += 1
        if in_string:
            self.errors.append(
                f"Unterminated string in Terraform file: {self._relative(path)}"
            )
        if depth != 0:
            self.errors.append(
                f"Unbalanced braces in Terraform file: {self._relative(path)}"
            )

    def optional_external_checks(self) -> list[str]:
        """Run installed external validators and report skipped tools explicitly."""
        results: list[str] = []
        commands = (
            ("terraform", ["terraform", "fmt", "-check", "-recursive", "infra/terraform"]),
            ("kubectl", ["kubectl", "kustomize", "deploy/kubernetes/overlays/local"]),
            ("docker", ["docker", "compose", "config", "--quiet"]),
        )
        for executable, command in commands:
            if self._which(executable) is None:
                results.append(f"SKIPPED {executable}: executable not installed")
                continue
            completed = subprocess.run(
                command,
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                message = completed.stderr.strip() or completed.stdout.strip()
                self.errors.append(f"External check failed ({' '.join(command)}): {message}")
            else:
                results.append(f"PASSED {' '.join(command)}")
        return results

    def _yaml_mapping(self, path: Path) -> dict[str, Any]:
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            self.errors.append(f"Invalid YAML {self._relative(path)}: {exc}")
            return {}
        if not isinstance(payload, dict):
            self.errors.append(f"YAML document must be a mapping: {self._relative(path)}")
            return {}
        return payload

    @classmethod
    def _find_values(cls, value: object, key: str) -> Iterable[str]:
        if isinstance(value, dict):
            for item_key, item_value in value.items():
                if item_key == key and isinstance(item_value, str):
                    yield item_value
                yield from cls._find_values(item_value, key)
        elif isinstance(value, list):
            for item in value:
                yield from cls._find_values(item, key)

    def _ignored(self, path: Path) -> bool:
        return bool(
            {".git", ".venv", ".local", "build", "dist", "__pycache__"}
            & set(path.relative_to(self.root).parts)
        )

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    @staticmethod
    def _which(executable: str) -> str | None:
        from shutil import which

        return which(executable)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--external", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    validator = RepositoryValidator(args.root)
    try:
        validator.run()
        external = validator.optional_external_checks() if args.external else []
        if validator.errors:
            raise ValidationFailure("\n".join(validator.errors))
    except ValidationFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Repository validation passed ({len(set(validator.checked))} files checked).")
    for result in external:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
