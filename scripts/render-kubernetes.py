#!/usr/bin/env python3
"""Render a Kustomize overlay and pin application containers to one OCI digest."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

_IMAGE = re.compile(r"^[a-zA-Z0-9._/:@-]+@sha256:[0-9a-f]{64}$")
_APP_CONTAINERS = frozenset({"api", "outbox-worker", "migrate"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prerequisite-output", type=Path, required=True)
    parser.add_argument("--migration-output", type=Path, required=True)
    return parser


def _render(overlay: Path) -> str:
    command = ["kubectl", "kustomize", str(overlay)]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Kustomize render failed: {message}")
    return completed.stdout


def _pin_document(document: dict[str, Any], image: str) -> dict[str, Any]:
    spec = document.get("spec")
    if not isinstance(spec, dict):
        return document
    kind = document.get("kind")
    if kind not in {"Deployment", "Job"}:
        return document
    template = spec.get("template")
    if not isinstance(template, dict):
        return document
    pod_spec = template.get("spec")
    if not isinstance(pod_spec, dict):
        return document
    containers = pod_spec.get("containers")
    if not isinstance(containers, list):
        return document
    for container in containers:
        if isinstance(container, dict) and container.get("name") in _APP_CONTAINERS:
            container["image"] = image
            container["imagePullPolicy"] = "IfNotPresent"
    return document


def _write(path: Path, documents: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump_all(documents, sort_keys=False, explicit_start=True)
    path.write_text(rendered, encoding="utf-8")


def main() -> int:
    args = _parser().parse_args()
    if _IMAGE.fullmatch(args.image) is None:
        print(
            "--image must be an immutable OCI reference ending in @sha256:<64 hex>",
            file=sys.stderr,
        )
        return 2
    try:
        raw = _render(args.overlay)
        parsed = [item for item in yaml.safe_load_all(raw) if isinstance(item, dict)]
        documents = [_pin_document(item, args.image) for item in parsed]
    except (OSError, RuntimeError, yaml.YAMLError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    migration = [item for item in documents if item.get("kind") == "Job"]
    workloads = [item for item in documents if item.get("kind") == "Deployment"]
    prerequisites = [
        item for item in documents if item.get("kind") not in {"Deployment", "Job"}
    ]
    if not migration:
        print("Rendered overlay contains no migration Job", file=sys.stderr)
        return 1
    if not workloads:
        print("Rendered overlay contains no Deployments", file=sys.stderr)
        return 1
    if not prerequisites:
        print("Rendered overlay contains no prerequisite resources", file=sys.stderr)
        return 1
    _write(args.prerequisite_output, prerequisites)
    _write(args.migration_output, migration)
    _write(args.output, workloads)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
