# Add a strongly typed domain value

**Exercise ID:** `python-domain-extension`
**Track:** `python-software-engineering`
**Difficulty:** `beginner`
**Expected focused sessions:** 3

## Objective

Add a validated domain value without coupling the domain layer to a framework.

## Prerequisites

- None

## Extension points

- `src/stock_predictor/domain/common/values.py`
- `tests/unit/domain/common`

## Acceptance criteria

- Reject invalid values with a domain exception.
- Preserve immutability and deterministic equality.
- Keep architecture-boundary tests passing.

## Verification

- `uv run --locked pytest tests/unit/domain/common tests/architecture`
- `uv run --locked pyright`

## Deliverables

- Typed value object
- Unit and property-based tests
- Short ADR note

## Review questions

- Which invariant does the change introduce or preserve?
- How does the implementation prevent future-data leakage or silent mutation?
- What happens when an input, dependency, or external provider fails?
- Which evidence proves the result is reproducible?
- What limitation remains after this exercise?
