# Pack 2A Simple Checklist (Do this line by line)

## Goal
Freeze data format before writing real modules.

## Step 0: open terminal in new repo
```bash
cd /Users/salmannajah/Developer/trace-ai/traceai_v2
```

## Step 1: read one file first
Open:
`docs/pack2a_canonical_data_contracts.md`

Read only these sections now:
1. `requirements`
2. `code_units`
3. `gold_links`
4. `predicted_links`
5. `runs`

## Step 2: compare with existing CSV files
Open and compare:
1. `data/raw/local_pilot/requirements.csv`
2. `data/raw/local_pilot/code_units.csv`
3. `data/raw/local_pilot/gold_links.csv`
4. `data/interim/predicted_links_template.csv`
5. `data/interim/runs_template.csv`

Check:
1. Column names are matching with contract doc.
2. Label values are valid.
3. There is no extra random field.

## Step 3: run quick line check
```bash
wc -l data/raw/local_pilot/requirements.csv
wc -l data/raw/local_pilot/code_units.csv
wc -l data/raw/local_pilot/gold_links.csv
wc -l data/interim/predicted_links_template.csv
wc -l data/interim/runs_template.csv
```

## Step 4: sign-off in one place
In `docs/pack2a_canonical_data_contracts.md`:
1. Add one line under Reviewer notes.
2. Tick `Approved` if clear.
3. If not clear, tick `Needs revision` and write what to change.

## Step 5: send this update
Send only these 3 lines:
1. `Pack 2A: Approved` or `Pack 2A: Needs revision`
2. `Field changes needed: <list or none>`
3. `Ready for Pack 2B: yes/no`
