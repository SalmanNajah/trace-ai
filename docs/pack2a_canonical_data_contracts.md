# Pack 2A - Dataset Structure (Simple + Detailed)

Last updated: 2026-04-12

## What is a data contract?
Very simple:
Data contract means fixed column names and fixed meaning.

Why we need this:
1. Backend, retrieval, and evaluation all must read same format.
2. If names keep changing, whole pipeline will break.
3. Report tables become easy when structure is fixed from day 1.

This pack is only for fixing data format.
No model tuning here.

---

## The 5 entities we will use
1. `requirements`
2. `code_units`
3. `gold_links`
4. `predicted_links`
5. `runs`

---

## 1) requirements

One row = one requirement statement.

Fields:
1. `project_id` (UUID)
2. `requirement_id` (UUID)
3. `req_key` (example: `REQ-001`)
4. `text` (full requirement sentence)
5. `source_doc` (example: `srs_v1.pdf`)
6. `version` (integer)
7. `created_at` (timestamp)

Sample:
```json
{
  "project_id": "11111111-1111-1111-1111-111111111111",
  "requirement_id": "22222222-2222-2222-2222-222222222222",
  "req_key": "REQ-001",
  "text": "The system shall allow users to upload requirement documents.",
  "source_doc": "srs_v1.pdf",
  "version": 1,
  "created_at": "2026-04-12T11:00:00Z"
}
```

---

## 2) code_units

One row = one code piece (function/class/method/file chunk).

Fields:
1. `project_id`
2. `code_unit_id`
3. `code_key` (example: `CODE-001`)
4. `file_path`
5. `symbol` (can be null for file-level chunk)
6. `start_line`
7. `end_line`
8. `language`
9. `chunk_type` (`function`, `method`, `class`, `file`)
10. `content` (code text)
11. `commit_sha` (null for local pilot)
12. `created_at`

Sample:
```json
{
  "project_id": "11111111-1111-1111-1111-111111111111",
  "code_unit_id": "33333333-3333-3333-3333-333333333333",
  "code_key": "CODE-001",
  "file_path": "backend/app/routers/requirements.py",
  "symbol": "upload_requirements",
  "start_line": 20,
  "end_line": 80,
  "language": "python",
  "chunk_type": "function",
  "content": "def upload_requirements(...): ...",
  "commit_sha": null,
  "created_at": "2026-04-12T11:05:00Z"
}
```

---

## 3) gold_links

One row = one true answer mapping.

Fields:
1. `project_id`
2. `gold_link_id`
3. `req_key`
4. `code_key`
5. `label`
6. `notes`
7. `created_at`

Allowed `label` values:
1. `Implemented`
2. `Partially Implemented`
3. `Missing`

Sample:
```json
{
  "project_id": "11111111-1111-1111-1111-111111111111",
  "gold_link_id": "44444444-4444-4444-4444-444444444444",
  "req_key": "REQ-001",
  "code_key": "CODE-001",
  "label": "Implemented",
  "notes": "Upload endpoint clearly implements this requirement.",
  "created_at": "2026-04-12T11:10:00Z"
}
```

---

## 4) predicted_links

One row = one link predicted by our pipeline.

Fields:
1. `project_id`
2. `prediction_id`
3. `requirement_id`
4. `code_unit_id`
5. `req_key`
6. `code_key`
7. `status`
8. `retrieval_score`
9. `rerank_score`
10. `final_score`
11. `confidence`
12. `explanation`
13. `run_id`
14. `created_at`

Allowed `status` values:
1. `Implemented`
2. `Partially Implemented`
3. `Missing`

Sample:
```json
{
  "project_id": "11111111-1111-1111-1111-111111111111",
  "prediction_id": "55555555-5555-5555-5555-555555555555",
  "requirement_id": "22222222-2222-2222-2222-222222222222",
  "code_unit_id": "33333333-3333-3333-3333-333333333333",
  "req_key": "REQ-001",
  "code_key": "CODE-001",
  "status": "Implemented",
  "retrieval_score": 0.78,
  "rerank_score": 0.83,
  "final_score": 0.81,
  "confidence": 0.82,
  "explanation": "Requirement and code both handle upload flow.",
  "run_id": "66666666-6666-6666-6666-666666666666",
  "created_at": "2026-04-12T11:15:00Z"
}
```

---

## 5) runs

One row = one full experiment run.

Fields:
1. `project_id`
2. `run_id`
3. `run_type` (`baseline`, `rerank`, `ablation`, `demo`)
4. `dataset_name`
5. `dataset_split`
6. `config_hash`
7. `started_at`
8. `ended_at`
9. `metrics_json`

`metrics_json` should store:
`precision`, `recall`, `f1`, `mrr`, `ndcg`, `top_k_recall`

Sample:
```json
{
  "project_id": "11111111-1111-1111-1111-111111111111",
  "run_id": "66666666-6666-6666-6666-666666666666",
  "run_type": "baseline",
  "dataset_name": "local_pilot",
  "dataset_split": "full",
  "config_hash": "f91f77b2c03f53f03ab5e391267df5e8",
  "started_at": "2026-04-12T11:20:00Z",
  "ended_at": "2026-04-12T11:25:00Z",
  "metrics_json": {
    "precision": 0.74,
    "recall": 0.69,
    "f1": 0.71,
    "mrr": 0.78,
    "ndcg": 0.75,
    "top_k_recall": 0.86
  }
}
```

---

## Manual steps you must do now (Pack 2A)
1. Open this file and check all field names.
2. Open `data/raw/local_pilot/requirements.csv` and verify it matches `requirements` idea.
3. Open `data/raw/local_pilot/code_units.csv` and verify it matches `code_units` idea.
4. Open `data/raw/local_pilot/gold_links.csv` and verify it matches `gold_links` idea.
5. Open `data/interim/predicted_links_template.csv` and verify it matches `predicted_links` fields.
6. Open `data/interim/runs_template.csv` and verify it matches `runs` fields.
7. If any name is confusing, write one-line note in sign-off section.
8. Mark Approved when clear.

---

## Rules (do not break)
1. `req_key` and `code_key` should be stable IDs.
2. Labels must come only from allowed values.
3. Every predicted link must have `run_id`.
4. Every run must save metrics.

---

## Sign-off checkpoint (Pack 2A)
- Reviewer notes:
- Decision:
  - [x] Approved
  - [ ] Needs revision
