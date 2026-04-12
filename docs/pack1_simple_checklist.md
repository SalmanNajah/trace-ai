# Pack 1 Simple Checklist

Use this exactly. No extra work.

## Pack 1A
1. Open `docs/phase1_scope.md`
2. Add one line in Reviewer notes.
3. Mark Decision as `Approved`.
4. Open `docs/dataset_registry.md`
5. Check that only local pilot dataset is listed.
6. Save.

## Pack 1B
1. Open `data/raw/local_pilot/requirements.csv`
2. Keep total 10 to 20 rows.
3. Open `data/raw/local_pilot/code_units.csv`
4. Keep total 20 to 40 rows.
5. Open `data/raw/local_pilot/gold_links.csv`
6. Add true mapping rows.
7. Label must be one of:
   - `Implemented`
   - `Partially Implemented`
   - `Missing`
8. Open `docs/dataset_mapping.md`
9. Add one line in Reviewer notes.
10. Mark Decision as `Approved`.
11. Stop. Do not start Pack 2 yet.

## Quick check commands
```bash
cd /Users/salmannajah/Developer/trace-ai/traceai_v2
wc -l data/raw/local_pilot/requirements.csv
wc -l data/raw/local_pilot/code_units.csv
wc -l data/raw/local_pilot/gold_links.csv
```

## What to send after Pack 1
1. requirements row count
2. code_units row count
3. gold_links row count
4. confirmation that 1A and 1B are approved

## Current expected counts
1. requirements.csv: 16 lines (1 header + 15 data rows)
2. code_units.csv: 29 lines (1 header + 28 data rows)
3. gold_links.csv: 26 lines (1 header + 25 data rows)
