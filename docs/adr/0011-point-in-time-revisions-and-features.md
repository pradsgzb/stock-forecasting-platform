# ADR-0011: Represent Corrections as Revisions and Compute Features at a Decision Cutoff

- Status: Accepted
- Date: 2026-11-03

## Context

A historical dataset can leak future information when later corrections, restatements, symbol
mappings, or corporate actions are treated as though they were known earlier. Destructively
updating a price history also prevents reproduction of earlier experiments.

## Decision

Append normalized bar revisions and deletion tombstones. Query the latest eligible revision as
known at an explicit UTC cutoff. Store corporate-action factors separately and apply only factor
revisions available by that cutoff. Feed leakage-checked numeric views into versioned feature
calculators, and use the same feature pipeline for historical and serving contexts.

## Consequences

The platform can reconstruct what a model could have known at a prior decision. Storage grows
with corrections, and every feature request must provide a decision cutoff; these costs are
accepted to preserve research integrity.
