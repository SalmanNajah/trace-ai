/**
 * Scoring constants and utilities for TraceAI trace link analysis.
 *
 * All similarity scores are cosine similarity from BAAI/bge-base-en-v1.5 embeddings
 * on cross-domain NL→code matching. Valid range: 0.0–1.0.
 * Domain gap (natural language vs code) means cosine similarity tops out ~0.65–0.70
 * for genuinely strong matches.
 */

/**
 * Backend label thresholds — must stay in sync with persistence.py _score_to_label().
 * These determine whether a requirement is marked Implemented, Partial, or Missing.
 */
export const LABEL_THRESHOLDS = {
  IMPLEMENTED: 0.50,
  PARTIAL: 0.38,
} as const;

/**
 * Frontend confidence buckets for the Mapping Quality Breakdown chart.
 * These are intentionally different from LABEL_THRESHOLDS — labels indicate
 * implementation status, while quality buckets indicate match confidence.
 */
export const QUALITY_THRESHOLDS = {
  STRONG: 0.65,
  MODERATE: 0.50,
  WEAK: 0.30,
} as const;

export type TraceLabel = "Implemented" | "Partial" | "Missing";

export type TraceLink = {
  code_unit_id: string;
  code_key: string;
  /** Cosine similarity between requirement and code embeddings. Range: 0.0–1.0 */
  score: number;
  /** Position among candidate matches for this requirement (1 = best) */
  rank: number;
  label: TraceLabel;
  explanation: string;
  file_path: string;
  symbol: string;
  start_line: number;
  end_line: number;
  content: string;
  is_correct?: boolean;
};

export type ProjectInfo = {
  project_id: string;
  name: string;
  description: string;
  repo_type: string;
  repo_path: string;
  github_url: string;
  branch: string;
  last_commit_sha: string;
  requirements_count: number;
  code_units_count: number;
  trace_links_count: number;
  created_at: string | null;
  last_run: string | null;
};

export type TraceMatrixRow = {
  requirement_id: string;
  req_key: string;
  text: string;
  best_label: TraceLabel;
  /** Cosine similarity of the top-ranked code match. Range: 0.0–1.0 */
  best_score: number;
  links: TraceLink[];
  is_correct_match?: boolean;
  has_gold?: boolean;
};

export type EvaluationMetrics = {
  has_gold: boolean;
  hit_at_k: number;
  mrr: number;
  ndcg_at_k: number;
  precision_at_k: number;
  recall_at_k: number;
  f1_at_k: number;
  map_score: number;
};

export type TraceMatrixResponse = {
  project_id: string;
  requirements_total: number;
  requirements_linked: number;
  requirements_implemented: number;
  /** Percentage of requirements labeled "Implemented" (0–100) */
  completion_percentage: number;
  /** Percentage of requirements with at least one trace link (0–100) */
  coverage_percentage: number;
  rows: TraceMatrixRow[];
  evaluation?: EvaluationMetrics;
};

export type AnalysisRun = {
  id: number;
  project_id: string;
  commit_sha: string | null;
  changed_files: string | null;
  requirements_count: number;
  code_units_count: number;
  trace_links_count: number;
  execution_time_seconds: number;
  created_at: string;
};

/** Clamp a raw score to 0.0–1.0 (guards against BM25/RRF scores leaking through) */
export function clampScore(score: number): number {
  return Math.min(Math.max(score, 0), 1);
}

/** Format a similarity score for display. Returns "—" for zero/negative scores. */
export function formatScore(score: number): string {
  if (score <= 0) return "—";
  return clampScore(score).toFixed(3);
}

/** Mean of best_score across all rows, clamped to 0–1. Returns "–" if no rows. */
export function computeAvgScore(rows: TraceMatrixRow[]): string {
  if (rows.length === 0) return "–";
  const sum = rows.reduce((acc, row) => acc + clampScore(row.best_score), 0);
  return (sum / rows.length).toFixed(3);
}

/** Count rows falling into each confidence quality bucket */
export function computeQualityBuckets(rows: TraceMatrixRow[]) {
  let strongMatch = 0;
  let moderateMatch = 0;
  let weakMatch = 0;
  let noMatch = 0;

  for (const r of rows) {
    const s = clampScore(r.best_score);
    if (s >= QUALITY_THRESHOLDS.STRONG) strongMatch++;
    else if (s >= QUALITY_THRESHOLDS.MODERATE) moderateMatch++;
    else if (s >= QUALITY_THRESHOLDS.WEAK && r.best_label !== "Missing") weakMatch++;
    else noMatch++;
  }

  return { strongMatch, moderateMatch, weakMatch, noMatch };
}

/** Count rows by implementation status label */
export function computeCoverageCounts(rows: TraceMatrixRow[]) {
  let implemented = 0;
  let partial = 0;
  let missing = 0;

  for (const r of rows) {
    if (r.best_label === "Implemented") implemented++;
    else if (r.best_label === "Partial") partial++;
    else missing++;
  }

  return { implemented, partial, missing };
}
