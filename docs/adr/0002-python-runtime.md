# ADR-0002: Use Python 3.14 as Preferred Runtime with a 3.13 Compatibility Floor

- Status: Accepted
- Date: 2026-11-03

## Context

Python 3.15 is newly released. The scientific ecosystem benefits from allowing a stabilization
period for compiled dependencies. Python 3.13 remains usable as a compatibility floor, while
3.14 has current binary installers and broader maturity.

## Decision

Use Python 3.14 for production and CI where available. Keep source compatible with Python 3.13
until an intentional floor upgrade. Declare `>=3.13,<3.15` in this foundation release.

## Consequences

The project avoids immediate adoption risk from a brand-new interpreter while retaining modern
typing and performance features. CI must test both supported minors.
