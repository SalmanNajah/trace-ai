"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

type TraceLink = {
  code_unit_id: string;
  code_key: string;
  score: number;
  rank: number;
  label: "Implemented" | "Partial" | "Missing";
  explanation: string;
  file_path: string;
  symbol: string;
  start_line: number;
  end_line: number;
  content: string;
};

type TraceMatrixRow = {
  requirement_id: string;
  req_key: string;
  text: string;
  best_label: "Implemented" | "Partial" | "Missing";
  best_score: number;
  links: TraceLink[];
};

type TraceMatrixResponse = {
  project_id: string;
  requirements_total: number;
  requirements_linked: number;
  requirements_implemented: number;
  completion_percentage: number;
  coverage_percentage: number;
  rows: TraceMatrixRow[];
};

type PipelineStep = "idle" | "resetting" | "uploading" | "ingesting" | "generating" | "done" | "error";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8100";

/* ------------------------------------------------------------------ */
/* Main Page                                                           */
/* ------------------------------------------------------------------ */

export default function Home() {
  const [projectId, setProjectId] = useState("demo-project");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [repoPath, setRepoPath] = useState("");

  // Pipeline state
  const [step, setStep] = useState<PipelineStep>("idle");
  const [stepMessage, setStepMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  // Results
  const [traceMatrix, setTraceMatrix] = useState<TraceMatrixResponse | null>(null);
  const [selectedRow, setSelectedRow] = useState<TraceMatrixRow | null>(null);
  const [reqCount, setReqCount] = useState(0);
  const [codeCount, setCodeCount] = useState(0);
  const [linkCount, setLinkCount] = useState(0);

  // Timer
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const elapsedRef = useRef(0);
  const [totalTime, setTotalTime] = useState<number | null>(null);

  function startTimer() {
    elapsedRef.current = 0;
    setElapsed(0);
    setTotalTime(null);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      elapsedRef.current += 1;
      setElapsed(elapsedRef.current);
    }, 1000);
  }

  function stopTimer() {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setTotalTime(elapsedRef.current);
  }

  // Load existing matrix on mount
  const loadMatrix = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/projects/${projectId}/trace-matrix`);
      if (res.ok) {
        const data = await res.json();
        setTraceMatrix(data as TraceMatrixResponse);
      }
    } catch { /* ignore */ }
  }, [projectId]);

  useEffect(() => {
    loadMatrix();
  }, [loadMatrix]);

  /* ---------------------------------------------------------------- */
  /* One-click pipeline                                                */
  /* ---------------------------------------------------------------- */

  async function runPipeline() {
    if (!uploadFile) {
      setErrorMessage("Please select a requirements document.");
      return;
    }
    if (!repoPath.trim()) {
      setErrorMessage("Please enter a repository path.");
      return;
    }

    setErrorMessage("");
    setTraceMatrix(null);
    setSelectedRow(null);
    startTimer();

    try {
      // Step 1: Reset
      setStep("resetting");
      setStepMessage("Resetting project data…");
      const resetRes = await fetch(`${API}/api/projects/${projectId}/reset`, { method: "POST" });
      if (!resetRes.ok) throw new Error("Reset failed");

      // Step 2: Upload requirements
      setStep("uploading");
      setStepMessage("Uploading & embedding requirements…");
      const body = new FormData();
      body.append("file", uploadFile);
      const uploadRes = await fetch(`${API}/api/projects/${projectId}/requirements/upload`, {
        method: "POST",
        body,
      });
      if (!uploadRes.ok) {
        const err = await uploadRes.json().catch(() => ({}));
        throw new Error(err.detail || `Upload failed: HTTP ${uploadRes.status}`);
      }
      const uploadData = await uploadRes.json();
      setReqCount(uploadData.persisted?.inserted_requirements || 0);

      // Step 3: Ingest code
      setStep("ingesting");
      setStepMessage("Parsing repository & embedding code…");
      const ingestRes = await fetch(`${API}/api/projects/${projectId}/repo/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_path: repoPath.trim() }),
      });
      if (!ingestRes.ok) {
        const err = await ingestRes.json().catch(() => ({}));
        throw new Error(err.detail || `Ingestion failed: HTTP ${ingestRes.status}`);
      }
      const ingestData = await ingestRes.json();
      setCodeCount(ingestData.persisted?.inserted_code_units || 0);

      // Step 4: Generate trace links
      setStep("generating");
      setStepMessage("Generating trace links with reranking…");
      const traceRes = await fetch(`${API}/api/projects/${projectId}/trace-links/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ top_k: 10 }),
      });
      if (!traceRes.ok) {
        const err = await traceRes.json().catch(() => ({}));
        throw new Error(err.detail || `Trace generation failed: HTTP ${traceRes.status}`);
      }
      const traceData = await traceRes.json();
      setLinkCount(traceData.generated?.links_generated || 0);

      // Step 5: Load results
      const matrixRes = await fetch(`${API}/api/projects/${projectId}/trace-matrix`);
      if (matrixRes.ok) {
        setTraceMatrix(await matrixRes.json());
      }

      stopTimer();
      setStep("done");
      setStepMessage("Analysis complete!");
    } catch (err) {
      stopTimer();
      setStep("error");
      setStepMessage("");
      setErrorMessage((err as Error).message);
    }
  }

  const isRunning = !["idle", "done", "error"].includes(step);

  /* ---------------------------------------------------------------- */
  /* Computed stats                                                    */
  /* ---------------------------------------------------------------- */

  const implemented = traceMatrix?.rows.filter((r) => r.best_label === "Implemented").length || 0;
  const partial = traceMatrix?.rows.filter((r) => r.best_label === "Partial").length || 0;
  const missing = traceMatrix?.rows.filter((r) => r.best_label === "Missing").length || 0;

  /* ---------------------------------------------------------------- */
  /* Render                                                            */
  /* ---------------------------------------------------------------- */

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-6 py-10">
      {/* Header */}
      <header className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent">
            <path d="M12 2L2 7l10 5 10-5-10-5Z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>
        <div>
          <h1 className="font-serif text-3xl tracking-tight">
            Trace<span className="text-accent">AI</span>
          </h1>
          <p className="text-xs text-foreground-muted">
            Automated requirements-to-code traceability
          </p>
        </div>
      </header>

      {/* Input Section */}
      <section className="rounded-2xl border border-border-subtle bg-surface p-6">
        <div className="grid gap-6 md:grid-cols-3">
          {/* Project ID */}
          <FieldLabel label="Project ID">
            <input
              className="w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm text-foreground focus:border-accent focus:ring-1 focus:ring-accent"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              placeholder="my-project"
              disabled={isRunning}
            />
          </FieldLabel>

          {/* Requirements Document */}
          <FieldLabel label="Requirements Document">
            <input
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground file:mr-3 file:rounded-md file:border-0 file:bg-surface-raised file:px-3 file:py-1 file:text-xs file:font-medium file:text-foreground-muted focus:border-accent focus:ring-1 focus:ring-accent"
              type="file"
              accept=".txt,.md,.pdf,.docx"
              onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              disabled={isRunning}
            />
          </FieldLabel>

          {/* Repository Path */}
          <FieldLabel label="Code Repository (local path)">
            <input
              className="w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm text-foreground focus:border-accent focus:ring-1 focus:ring-accent"
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
              placeholder="/path/to/repository"
              disabled={isRunning}
            />
          </FieldLabel>
        </div>

        {/* Action Button + Status */}
        <div className="mt-6 flex flex-wrap items-center gap-4">
          <button
            className="rounded-xl bg-accent px-8 py-3 text-sm font-semibold text-white shadow-lg shadow-accent/20 transition-all hover:bg-accent-hover hover:shadow-accent/30 disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={runPipeline}
            disabled={isRunning}
          >
            {isRunning ? "Analyzing…" : "🚀 Analyze Traceability"}
          </button>

          {/* Pipeline progress */}
          {isRunning && (
            <div className="flex items-center gap-3 text-sm">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
              <span className="text-accent">{stepMessage}</span>
              {elapsed > 0 && (
                <span className="tabular-nums text-foreground-muted">{elapsed}s</span>
              )}
            </div>
          )}

          {step === "done" && (
            <div className="flex items-center gap-2 text-sm text-success">
              <span>✓</span>
              <span>{stepMessage}</span>
              {totalTime != null && (
                <span className="tabular-nums text-foreground-muted">
                  in {totalTime}s
                </span>
              )}
            </div>
          )}

          {errorMessage && (
            <div className="text-sm text-error">{errorMessage}</div>
          )}
        </div>

        {/* Pipeline steps indicator */}
        {isRunning && <PipelineSteps currentStep={step} />}
      </section>

      {/* Stats Cards */}
      {(traceMatrix || step === "done") && (
        <div className="grid gap-4 sm:grid-cols-5 stagger-item">
          <StatCard
            label="Requirements"
            value={reqCount || traceMatrix?.requirements_total || 0}
            info="Number of functional requirements extracted from the uploaded document after filtering headers and noise."
          />
          <StatCard
            label="Code Units"
            value={codeCount}
            info="Number of code chunks (functions, classes, methods) parsed from the repository using tree-sitter."
          />
          <StatCard
            label="Trace Links"
            value={linkCount}
            info={`Total requirement-to-code links generated. Each requirement gets top-10 matches (${reqCount || traceMatrix?.requirements_total || 0} × 10 = ${linkCount}).`}
          />
          <StatCard
            label="Implemented"
            value={traceMatrix ? `${traceMatrix.completion_percentage.toFixed(1)}%` : "–"}
            highlight
            info="Percentage of requirements with a strong semantic match to code (embedding similarity ≥ 0.50)."
          />
          <StatCard
            label="Avg Score"
            value={traceMatrix && traceMatrix.rows.length > 0
              ? (traceMatrix.rows.reduce((s, r) => s + r.best_score, 0) / traceMatrix.rows.length).toFixed(3)
              : "–"}
            info="Mean best-match cosine similarity across all requirements. For NL→code matching, 0.50+ is strong, 0.65+ is excellent."
          />
        </div>
      )}

      {/* Summary Bar */}
      {traceMatrix && traceMatrix.rows.length > 0 && (
        <div className="flex items-center gap-6 rounded-xl border border-border-subtle bg-surface px-5 py-3 text-xs stagger-item">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
            Implemented: {implemented}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-amber-400" />
            Partial: {partial}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-red-400" />
            Missing: {missing}
          </span>
          <span className="ml-auto text-foreground-subtle">
            {traceMatrix.requirements_linked}/{traceMatrix.requirements_total} requirements linked
          </span>
        </div>
      )}

      {/* Trace Matrix Table */}
      {traceMatrix && traceMatrix.rows.length > 0 && (
        <section className="rounded-2xl border border-border-subtle bg-surface stagger-item">
          <div className="flex items-center justify-between border-b border-border-subtle px-5 py-3.5">
            <h2 className="font-serif text-lg">Traceability Matrix</h2>
            <span className="text-xs text-foreground-subtle">
              {traceMatrix.rows.length} requirements
            </span>
          </div>
          <div className="overflow-auto" style={{ maxHeight: "520px" }}>
            <table className="min-w-full text-sm">
              <thead className="sticky top-0 bg-surface z-10">
                <tr className="border-b border-border-subtle text-left text-xs uppercase tracking-wide text-foreground-subtle">
                  <th className="px-4 py-3">Requirement</th>
                  <th className="px-4 py-3">Best Match</th>
                  <th className="px-4 py-3 text-right">Score</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Links</th>
                </tr>
              </thead>
              <tbody>
                {traceMatrix.rows.map((row) => (
                  <tr
                    key={row.requirement_id}
                    className="cursor-pointer border-b border-border-subtle/50 transition-colors hover:bg-surface-raised/50"
                    onClick={() => setSelectedRow(row)}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-foreground">{row.req_key}</div>
                      <div className="mt-0.5 max-w-md truncate text-xs text-foreground-muted">
                        {row.text}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {row.links.length > 0 ? (
                        <div className="font-mono text-foreground-muted">
                          {row.links[0].file_path.split("/").pop()}
                          <span className="text-foreground-subtle">
                            :{row.links[0].start_line}
                          </span>
                        </div>
                      ) : (
                        <span className="text-foreground-subtle">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-foreground-muted">
                      {row.best_score > 0 ? row.best_score.toFixed(3) : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusPill label={row.best_label} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="rounded-full bg-surface-raised px-2 py-0.5 text-xs tabular-nums text-foreground-muted">
                        {row.links.length}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Footer */}
      <footer className="mt-auto border-t border-border-subtle pt-6 pb-4 text-center text-xs text-foreground-subtle">
        TraceAI — Automated Requirements Traceability · Local-first · BGE + Cross-Encoder
      </footer>

      {/* Detail Modal */}
      {selectedRow && (
        <DetailModal row={selectedRow} onClose={() => setSelectedRow(null)} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Pipeline Steps Indicator                                            */
/* ------------------------------------------------------------------ */

function PipelineSteps({ currentStep }: { currentStep: PipelineStep }) {
  const steps: { key: PipelineStep; label: string }[] = [
    { key: "resetting", label: "Reset" },
    { key: "uploading", label: "Requirements" },
    { key: "ingesting", label: "Code Analysis" },
    { key: "generating", label: "Trace Links" },
  ];

  const currentIdx = steps.findIndex((s) => s.key === currentStep);

  return (
    <div className="mt-5 flex items-center gap-2">
      {steps.map((s, i) => {
        const isDone = i < currentIdx;
        const isActive = i === currentIdx;
        return (
          <div key={s.key} className="flex items-center gap-2">
            <div
              className={`flex h-7 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition-all ${
                isDone
                  ? "bg-success/10 text-success"
                  : isActive
                    ? "bg-accent/10 text-accent"
                    : "bg-surface-raised text-foreground-subtle"
              }`}
            >
              {isDone ? "✓" : isActive ? (
                <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
              ) : (
                <span className="text-foreground-subtle/50">{i + 1}</span>
              )}
              <span>{s.label}</span>
            </div>
            {i < steps.length - 1 && (
              <div className={`h-px w-6 ${isDone ? "bg-success/30" : "bg-border-subtle"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Detail Modal — requirement + best code match                        */
/* ------------------------------------------------------------------ */

function DetailModal({ row, onClose }: { row: TraceMatrixRow; onClose: () => void }) {
  const backdropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", handleKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const bestLink = row.links[0] || null;
  const implPercent = Math.round(row.best_score * 100);
  const progressColor =
    row.best_label === "Implemented"
      ? "bg-emerald-400"
      : row.best_label === "Partial"
        ? "bg-amber-400"
        : "bg-red-400";

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={(e) => { if (e.target === backdropRef.current) onClose(); }}
    >
      <div className="flex max-h-[90vh] w-full max-w-4xl flex-col rounded-2xl border border-border bg-surface shadow-2xl">
        {/* Header with close */}
        <div className="flex items-center justify-between border-b border-border-subtle px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="rounded-lg bg-accent/10 px-3 py-1 text-sm font-semibold text-accent">
              {row.req_key}
            </span>
            <StatusPill label={row.best_label} />
            <span className="text-2xl font-bold tabular-nums">{implPercent}%</span>
          </div>
          <button
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-border-subtle text-foreground-muted hover:bg-surface-raised hover:text-foreground"
            onClick={onClose}
          >
            ×
          </button>
        </div>

        {/* Implementation bar */}
        <div className="px-6 py-3 border-b border-border-subtle">
          <div className="flex items-center justify-between text-xs text-foreground-subtle mb-1.5">
            <span>Implementation Confidence</span>
            <span className="tabular-nums">{row.best_score.toFixed(3)}</span>
          </div>
          <div className="h-2 w-full rounded-full bg-surface-raised overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${progressColor}`}
              style={{ width: `${implPercent}%` }}
            />
          </div>
        </div>

        <div className="flex-1 overflow-auto">
          {/* Requirement section */}
          <div className="border-b border-border-subtle px-6 py-4">
            <div className="text-[10px] font-medium uppercase tracking-wider text-accent/70 mb-2">
              Requirement
            </div>
            <p className="text-sm leading-relaxed text-foreground">{row.text}</p>
          </div>

          {/* Best matched code */}
          {bestLink ? (
            <div className="px-6 py-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className="text-[10px] font-medium uppercase tracking-wider text-emerald-400/70">
                    Best Matched Code
                  </div>
                  <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-400">
                    {bestLink.file_path.split("/").pop()}
                  </span>
                </div>
                <span className="text-xs text-foreground-subtle">
                  {bestLink.symbol} · lines {bestLink.start_line}–{bestLink.end_line}
                </span>
              </div>
              <pre className="overflow-x-auto rounded-xl border border-border-subtle bg-background p-4 font-mono text-xs leading-6 text-foreground-muted">
                <code>{bestLink.content || "Code content not available."}</code>
              </pre>
            </div>
          ) : (
            <div className="py-12 text-center text-sm text-foreground-subtle">
              No matching code found for this requirement.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Shared Components                                                   */
/* ------------------------------------------------------------------ */

function StatusPill({ label }: { label: "Implemented" | "Partial" | "Missing" }) {
  const cls =
    label === "Implemented"
      ? "bg-emerald-500/15 text-emerald-300"
      : label === "Partial"
        ? "bg-amber-500/15 text-amber-300"
        : "bg-red-500/15 text-red-300";
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>{label}</span>;
}

function FieldLabel({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1.5">
      <span className="text-xs font-medium text-foreground-subtle">{label}</span>
      {children}
    </label>
  );
}

function StatCard({ label, value, highlight, info }: { label: string; value: string | number; highlight?: boolean; info?: string }) {
  return (
    <div className={`group relative rounded-xl border p-4 ${highlight ? "border-accent/30 bg-accent/5" : "border-border-subtle bg-surface"}`}>
      <div className="flex items-center gap-1.5">
        <div className="text-xs font-medium uppercase tracking-wider text-foreground-subtle">{label}</div>
        {info && (
          <div className="relative">
            <span className="cursor-help text-foreground-subtle/50 hover:text-foreground-muted transition-colors text-[10px]">ⓘ</span>
            <div className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 w-56 -translate-x-1/2 rounded-lg border border-border bg-surface-raised px-3 py-2 text-[11px] leading-relaxed text-foreground-muted opacity-0 shadow-xl transition-opacity group-hover:pointer-events-auto group-hover:opacity-100">
              {info}
              <div className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-border" />
            </div>
          </div>
        )}
      </div>
      <div className={`mt-1 text-2xl font-bold tabular-nums tracking-tight ${highlight ? "text-accent" : ""}`}>
        {value}
      </div>
    </div>
  );
}
