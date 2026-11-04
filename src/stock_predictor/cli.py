"""Command-line operations, diagnostics, delivery, labs, and reference execution."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from stock_predictor import __version__
from stock_predictor.adapters.security.jwt_authenticator import (
    JwtAuthenticator,
    JwtValidationPolicy,
)
from stock_predictor.api.app import create_api_app
from stock_predictor.application.delivery.service import (
    ArtifactInput,
    ReleaseManifestService,
)
from stock_predictor.application.learning.catalog import LearningCatalogService
from stock_predictor.application.workers.outbox import run_outbox_worker
from stock_predictor.bootstrap.container import build_container
from stock_predictor.bootstrap.logging import configure_logging
from stock_predictor.bootstrap.migrations import current_revision, upgrade_database
from stock_predictor.bootstrap.settings import load_settings
from stock_predictor.domain.common.errors import DomainError
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.delivery.models import ArtifactKind, DeploymentEnvironment
from stock_predictor.domain.learning.models import LearningTrack
from stock_predictor.domain.market.calendar import TradingSession
from stock_predictor.domain.market.identifiers import MarketIdentifierCode
from stock_predictor.reference.service import ReferenceScenarioService

_MEDIA_TYPES = {
    ArtifactKind.PYTHON_WHEEL: "application/zip",
    ArtifactKind.SOURCE_DISTRIBUTION: "application/gzip",
    ArtifactKind.CONTAINER_IMAGE: "application/vnd.oci.image.manifest.v1+json",
    ArtifactKind.DEPENDENCY_SBOM: "application/vnd.cyclonedx+json",
    ArtifactKind.CHECKSUMS: "text/plain",
    ArtifactKind.MODEL_PACKAGE: "application/octet-stream",
    ArtifactKind.DEPLOYMENT_BUNDLE: "application/zip",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock-predictor",
        description="Governed stock-forecasting research and paper-evaluation platform.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Validate configuration and dependency composition.")

    session = subparsers.add_parser("session", help="Display a regular trading session.")
    session.add_argument("--mic", required=True, help="ISO 10383 MIC, e.g. XNYS or XBOM.")
    session.add_argument("--date", required=True, help="Exchange-local date, YYYY-MM-DD.")

    phase = subparsers.add_parser("phase", help="Classify market phase at an instant.")
    phase.add_argument("--mic", required=True)
    phase.add_argument("--instant", required=True, help="ISO-8601 aware instant.")

    subparsers.add_parser("db-upgrade", help="Apply controlled Alembic migrations.")
    subparsers.add_parser("db-current", help="Display the operational schema revision.")
    subparsers.add_parser("serve", help="Run the authenticated internal API.")

    worker = subparsers.add_parser("worker", help="Dispatch transactional outbox events.")
    worker.add_argument("--once", action="store_true", help="Dispatch once and exit.")
    worker.add_argument("--limit", type=int, default=100)
    worker.add_argument("--poll-seconds", type=float, default=5.0)

    reference = subparsers.add_parser(
        "reference-scenario",
        help="Run the deterministic end-to-end research and MLOps scenario.",
    )
    reference.add_argument("--workspace", type=Path, default=Path(".local/reference"))
    reference.add_argument(
        "--output",
        type=Path,
        default=Path(".local/reference/reference-report.json"),
    )

    labs = subparsers.add_parser("labs", help="Inspect the packaged learning exercises.")
    lab_commands = labs.add_subparsers(dest="labs_command", required=True)
    lab_list = lab_commands.add_parser("list", help="List exercises in prerequisite order.")
    lab_list.add_argument("--track", choices=[item.value for item in LearningTrack])
    lab_list.add_argument("--catalog", type=Path)
    lab_show = lab_commands.add_parser("show", help="Show one exercise.")
    lab_show.add_argument("exercise_id")
    lab_show.add_argument("--catalog", type=Path)
    lab_validate = lab_commands.add_parser("validate", help="Validate the complete catalog.")
    lab_validate.add_argument("--catalog", type=Path)

    release = subparsers.add_parser(
        "release-manifest",
        help="Create, verify, or plan promotion of immutable release evidence.",
    )
    release_commands = release.add_subparsers(dest="release_command", required=True)
    create = release_commands.add_parser("create", help="Create a release manifest.")
    create.add_argument("--version", required=True)
    create.add_argument("--git-commit", required=True)
    create.add_argument("--source-root", type=Path, default=Path("."))
    create.add_argument("--build-run-id", required=True)
    create.add_argument(
        "--artifact",
        action="append",
        required=True,
        metavar="KIND=PATH",
        help="Repeat for wheel, sdist, SBOM, checksums, image manifest, or bundle.",
    )
    create.add_argument(
        "--gate",
        action="append",
        required=True,
        metavar="NAME=EVIDENCE",
        help="Record a passing quality gate and its evidence reference.",
    )
    create.add_argument("--output", type=Path, required=True)

    verify = release_commands.add_parser("verify", help="Verify a release manifest.")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--artifact-root", type=Path)

    plan = release_commands.add_parser("plan", help="Create a controlled promotion plan.")
    plan.add_argument("--manifest", type=Path, required=True)
    plan.add_argument("--source", choices=[item.value for item in DeploymentEnvironment])
    plan.add_argument(
        "--target",
        required=True,
        choices=[item.value for item in DeploymentEnvironment],
    )
    plan.add_argument("--image-digest", required=True)
    plan.add_argument("--rollback-release")
    plan.add_argument("--requested-by", required=True)
    return parser


def _session_payload(session: TradingSession) -> dict[str, object]:
    if not isinstance(session, TradingSession):
        raise TypeError("Expected a TradingSession")
    return {
        "exchange_mic": str(session.exchange_mic),
        "session_date": session.session_date.isoformat(),
        "opens_at": session.opens_at.isoformat(),
        "closes_at": session.closes_at.isoformat(),
        "breaks": [
            {"starts_at": item.starts_at.isoformat(), "ends_at": item.ends_at.isoformat()}
            for item in session.breaks
        ],
        "regular_trading_seconds": int(session.regular_trading_duration.total_seconds()),
    }


def _key_value(raw: str, *, field_name: str) -> tuple[str, str]:
    key, separator, value = raw.partition("=")
    if not separator or not key.strip() or not value.strip():
        raise ValueError(f"{field_name} must use NAME=VALUE syntax")
    return key.strip(), value.strip()


def _artifact_inputs(values: Sequence[str]) -> tuple[ArtifactInput, ...]:
    result: list[ArtifactInput] = []
    for raw in values:
        kind_raw, path_raw = _key_value(raw, field_name="Artifact")
        kind = ArtifactKind(kind_raw)
        result.append(
            ArtifactInput(
                path=Path(path_raw),
                kind=kind,
                media_type=_MEDIA_TYPES[kind],
            )
        )
    return tuple(result)


def _lab_payload(args: argparse.Namespace) -> dict[str, object]:
    service = LearningCatalogService(args.catalog)
    catalog = service.load()
    if args.labs_command == "validate":
        return service.summary()
    if args.labs_command == "show":
        exercise = catalog.get(args.exercise_id)
        return {
            "exercise_id": exercise.exercise_id,
            "title": exercise.title,
            "track": exercise.track.value,
            "difficulty": exercise.difficulty.value,
            "objective": exercise.objective,
            "prerequisites": list(exercise.prerequisites),
            "extension_points": list(exercise.extension_points),
            "acceptance_criteria": list(exercise.acceptance_criteria),
            "verification_commands": list(exercise.verification_commands),
            "deliverables": list(exercise.deliverables),
            "expected_sessions": exercise.expected_sessions,
        }
    selected = catalog.ordered()
    if args.track:
        track = LearningTrack(args.track)
        selected = tuple(item for item in selected if item.track is track)
    return {
        "schema_version": catalog.schema_version,
        "exercises": [
            {
                "exercise_id": item.exercise_id,
                "title": item.title,
                "track": item.track.value,
                "difficulty": item.difficulty.value,
                "prerequisites": list(item.prerequisites),
            }
            for item in selected
        ],
    }


def _release_payload(
    args: argparse.Namespace,
    service: ReleaseManifestService,
) -> dict[str, object]:
    if args.release_command == "create":
        normalized_gates = tuple(
            (name, True, evidence)
            for name, evidence in (
                _key_value(item, field_name="Gate") for item in args.gate
            )
        )
        manifest = service.create(
            release_version=args.version,
            git_commit=args.git_commit,
            source_root=args.source_root,
            build_run_id=args.build_run_id,
            artifacts=_artifact_inputs(args.artifact),
            gate_results=normalized_gates,
        )
        service.write(args.output, manifest)
        return {"manifest": str(args.output), **service.to_dict(manifest)}
    manifest = service.read(args.manifest)
    if args.release_command == "verify":
        service.verify(manifest, args.artifact_root)
        return {
            "manifest": str(args.manifest),
            "fingerprint": manifest.fingerprint,
            "verified": True,
        }
    source = None if args.source is None else DeploymentEnvironment(args.source)
    plan = service.plan_promotion(
        manifest,
        source=source,
        target=DeploymentEnvironment(args.target),
        image_digest_sha256=args.image_digest.removeprefix("sha256:"),
        rollback_release_fingerprint=args.rollback_release,
        requested_by=args.requested_by,
    )
    return {
        "release_fingerprint": plan.release_fingerprint,
        "source": None if plan.source is None else plan.source.value,
        "target": plan.target.value,
        "image_digest_sha256": plan.image_digest_sha256,
        "rollback_release_fingerprint": plan.rollback_release_fingerprint,
        "approval_required": plan.approval_required,
        "requested_by": plan.requested_by,
        "requested_at": plan.requested_at.isoformat(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        configure_logging(settings.app.log_level, settings.app.environment)

        if args.command == "labs":
            payload = _lab_payload(args)
        elif args.command == "reference-scenario":
            report = ReferenceScenarioService().run(args.workspace)
            report.write(args.output)
            payload = {"output": str(args.output), **report.to_dict()}
        else:
            container = build_container(settings)
            if args.command == "doctor":
                payload = {
                    "version": __version__,
                    "settings": settings.safe_summary(),
                    "exchanges": [
                        {
                            "mic": str(exchange.mic),
                            "name": exchange.name,
                            "timezone": exchange.timezone_name,
                            "calendar": exchange.calendar_name,
                        }
                        for exchange in container.exchanges.all()
                    ],
                }
            elif args.command == "session":
                mic = MarketIdentifierCode(args.mic)
                session_date = date.fromisoformat(args.date)
                payload = _session_payload(container.calendars.session(mic, session_date))
            elif args.command == "phase":
                mic = MarketIdentifierCode(args.mic)
                instant = UtcInstant.parse(args.instant)
                payload = {
                    "exchange_mic": str(mic),
                    "instant": instant.isoformat(),
                    "phase": container.market_time_service.phase(mic, instant).value,
                }
            elif args.command == "db-upgrade":
                upgrade_database(settings.database.url)
                payload = {"database": "upgraded", "revision": "head"}
            elif args.command == "db-current":
                revision = current_revision(settings.database.url)
                payload = {"database": "current revision", "revision": revision}
            elif args.command == "worker":
                result = run_outbox_worker(
                    container.outbox_dispatcher,
                    limit=args.limit,
                    poll_seconds=args.poll_seconds,
                    once=args.once,
                )
                payload = {
                    "selected": result.selected,
                    "published": result.published,
                    "failed": result.failed,
                    "dead_lettered": result.dead_lettered,
                }
            elif args.command == "release-manifest":
                payload = _release_payload(args, ReleaseManifestService(container.clock))
            elif args.command == "serve":
                settings.validate_api_runtime()
                app = create_api_app(
                    container,
                    JwtAuthenticator(
                        JwtValidationPolicy(
                            issuer=settings.api.jwt_issuer,
                            audience=settings.api.jwt_audience,
                            verification_key=settings.api_verification_key(),
                            algorithms=settings.api.jwt_algorithms,
                        )
                    ),
                )
                uvicorn.run(
                    app,
                    host=settings.api.host,
                    port=settings.api.port,
                    access_log=False,
                    server_header=False,
                    proxy_headers=False,
                )
                return 0
            else:  # pragma: no cover - argparse constrains the command.
                parser.error(f"Unsupported command: {args.command}")
                return 2
    except (DomainError, ValidationError, OSError, ValueError) as exc:
        parser.exit(status=2, message=f"error: {exc}\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
