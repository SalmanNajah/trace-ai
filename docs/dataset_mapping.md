# Dataset Mapping (Pack 1)

Last updated: 2026-04-12

This file tells exactly how to fill Pack 1 data files.
No external dataset now.

## Dataset root
`traceai_v2/data/raw/local_pilot/`

## File 1: `requirements.csv`
Use this for requirement statements.

Required columns:
`req_key,text,source_doc,version`

Example row:
`REQ-001,The system shall allow users to upload requirement documents.,srs_v1.pdf,1`

## File 2: `code_units.csv`
Use this for code pieces.

Required columns:
`code_key,file_path,symbol,start_line,end_line,language,chunk_type,content`

Example row:
`CODE-001,backend/app/routers/requirements.py,upload_requirements,20,80,python,function,"def upload_requirements(...): pass"`

## File 3: `gold_links.csv`
Use this for true mapping between requirements and code.

Required columns:
`req_key,code_key,label,notes`

Example row:
`REQ-001,CODE-001,Implemented,Requirement upload endpoint handles this behavior.`

## Allowed label values
`Implemented`
`Partially Implemented`
`Missing`

## Simple meaning
1. `requirements.csv` = what system should do.
2. `code_units.csv` = where this behavior is in code.
3. `gold_links.csv` = correct answer mapping for evaluation.

## Manual work you do now
1. Keep 10 to 20 requirement rows in `requirements.csv`.
2. Keep 20 to 40 code rows in `code_units.csv`.
3. Add true links in `gold_links.csv`.
4. Save all files.

## Sign-off checkpoint (Pack 1B)
- Reviewer notes:
- Decision:
  - [x] Approved
  - [ ] Needs revision
