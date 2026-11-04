# Student learning framework

The learning framework turns the production codebase into a structured curriculum without leaving unfinished production code in the main path.

## Rules

1. Start from a passing main branch.
2. Work on one exercise in a separate branch.
3. Read the declared extension points before editing.
4. Add or update tests before requesting review.
5. Keep all paper-trading and human-approval safeguards intact.
6. Record failed hypotheses and unsuccessful experiments.
7. Never use real brokerage credentials or deploy capital.

## Discover exercises

```bash
uv run --locked stock-predictor labs validate
uv run --locked stock-predictor labs list
uv run --locked stock-predictor labs show python-domain-extension
```

## Tracks

| Track | Focus |
|---|---|
| Python and software engineering | Strong types, boundaries, tests, maintainability |
| Data engineering | Provider adapters, immutable ingestion, quality, lineage |
| Time-series modeling | Point-in-time features and leakage prevention |
| Machine learning | Model plugins, baselines, evaluation, reproducibility |
| Deep learning | Bounded optional neural candidates |
| Financial modeling | Cost-aware simulation and accounting invariants |
| MLOps | Drift, model lifecycle, promotion, rollback |
| Cloud and DevOps | Containers, Kubernetes, Terraform, delivery controls |
| Research methodology | Replication, uncertainty, failed trials, limitations |

## Exercise documents

The Markdown exercise briefs in [`exercises/`](exercises/) are generated from the packaged, versioned catalog in `src/stock_predictor/resources/learning_catalog.json`. The JSON catalog is the source of truth used by the CLI.

## Review rubric

A completed exercise should demonstrate:

- correctness under normal and failure conditions;
- adherence to architecture boundaries;
- deterministic and reproducible behavior;
- explicit data and model lineage;
- security and privacy by default;
- adequate tests and documentation;
- honest limitations; and
- no weakening of research-only or paper-trading restrictions.
