# Dataset Registry (Pack 1)

Last updated: 2026-04-12

Pack 1 uses only one dataset.

## Dataset name
Local Pilot Dataset

## Why this dataset
This is simple and fully in your control.
You already understand this project context, so this is best for Phase 1 progress.

## Location
`traceai_v2/data/raw/local_pilot/`

## Files inside this dataset
1. `requirements.csv`
This file stores requirement statements.
2. `code_units.csv`
This file stores code pieces (functions/classes/pages).
3. `gold_links.csv`
This file stores true mapping between requirement and code.

## Status
Locked for Pack 1.
No external dataset now.

## Rules (must follow)
1. Edit only these 3 CSV files.
2. Do not change column names.
3. In `gold_links.csv`, label must be exactly one of these:
`Implemented`, `Partially Implemented`, `Missing`

## Pack 1A is complete when
1. You confirm this file is clear.
2. You keep only this local dataset for Pack 1.
