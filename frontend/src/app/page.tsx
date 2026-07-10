"use client";

import { useEffect, useRef, useState } from "react";
import {
  type ProjectInfo,
  type TraceMatrixRow,
  type TraceMatrixResponse,
  type AnalysisRun,
  type TraceLabel,
  clampScore,
  formatScore,
  computeAvgScore,
  computeQualityBuckets,
  computeCoverageCounts,
  QUALITY_THRESHOLDS,
} from "@/lib/tracing";

type PipelineStep = "idle" | "resetting" | "uploading" | "ingesting" | "generating" | "done" | "error";

type AppView = "landing" | "create" | "analysis";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8100";

export default function Home() {
  const [view, setView] = useState<AppView>("landing");
  const [activeProject, setActiveProject] = useState<ProjectInfo | null>(null);
  const [isViewingHistory, setIsViewingHistory] = useState(false);
  const [allProjects, setAllProjects] = useState<ProjectInfo[]>([]);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [repoPath, setRepoPath] = useState("");

  const [step, setStep] = useState<PipelineStep>("idle");
  const [stepMessage, setStepMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  const [traceMatrix, setTraceMatrix] = useState<TraceMatrixResponse | null>(null);
  const [selectedRow, setSelectedRow] = useState<TraceMatrixRow | null>(null);
  const [reqCount, setReqCount] = useState(0);
  const [codeCount, setCodeCount] = useState(0);
  const [linkCount, setLinkCount] = useState(0);

  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const elapsedRef = useRef(0);
  const [totalTime, setTotalTime] = useState<number | null>(null);
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");
  const [activeRunId, setActiveRunId] = useState<number | null>(null);

  async function handleSelectRun(runId: number) {
    if (!activeProject) return;
    setActiveRunId(runId);
    setTraceMatrix(null);
    setStepMessage("Loading historic run...");
    setStep("resetting");
    try {
      const res = await fetch(`${API}/api/projects/${activeProject.project_id}/trace-matrix?run_id=${runId}`);
      if (res.ok) {
        setTraceMatrix(await res.json());
        setStep("done");
        setStepMessage("Loaded historic run");
      } else {
        setStep("idle");
      }
    } catch (e) {
      setErrorMessage((e as Error).message);
      setStep("error");
    }
  }

  async function fetchProjectRuns(projectId: string) {
    try {
      const res = await fetch(`${API}/api/projects/${projectId}/runs`);
      if (res.ok) {
        setRuns(await res.json());
      }
    } catch {}
  }

  useEffect(() => {
    Promise.resolve().then(() => {
      if (activeProject) {
        fetchProjectRuns(activeProject.project_id);
      } else {
        setRuns([]);
      }
    });
  }, [activeProject]);

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

  async function fetchProjects() {
    try {
      const res = await fetch(`${API}/api/projects`);
      if (res.ok) {
        setAllProjects(await res.json());
      }
    } catch { /* ignore */ }
  }

  useEffect(() => {
    Promise.resolve().then(() => {
      fetchProjects();
    });
  }, []);

  async function handleDeleteProject(pid: string) {
    if (!confirm(`Are you sure you want to delete the project "${pid}"?`)) return;
    try {
      const res = await fetch(`${API}/api/projects/${pid}/reset`, { method: 'POST' });
      if (res.ok) {
        fetchProjects();
      }
    } catch (e) {
      console.error("Failed to delete project", e);
    }
  }

  async function handleDeleteAll() {
    if (!confirm("Are you sure you want to delete ALL projects? This cannot be undone.")) return;
    try {
      const res = await fetch(`${API}/api/projects`, { method: 'DELETE' });
      if (res.ok) {
        setAllProjects([]);
      }
    } catch (e) {
      console.error("Failed to delete all projects", e);
    }
  }

  async function handleSyncProject() {
    if (!activeProject) return;
    setIsSyncing(true);
    setSyncMessage("");
    setErrorMessage("");

    try {
      const res = await fetch(`${API}/api/projects/${activeProject.project_id}/sync`, {
        method: "POST"
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Sync failed");
      }
      const data = await res.json();
      if (data.reanalyzed) {
        const matrixRes = await fetch(`${API}/api/projects/${activeProject.project_id}/trace-matrix`);
        if (matrixRes.ok) {
          setTraceMatrix(await matrixRes.json());
        }

        const projRes = await fetch(`${API}/api/projects/${activeProject.project_id}`);
        if (projRes.ok) {
          setActiveProject(await projRes.json());
        }

        fetchProjectRuns(activeProject.project_id);

        const filesCount = data.changed_files.length;
        setSyncMessage(
          `Synced! ${filesCount} file${filesCount === 1 ? "" : "s"} changed (Commit: ${data.new_commit.slice(0, 7)}).`
        );
      } else {
        setSyncMessage("Already up to date with the latest commit.");
      }
    } catch (e) {
      setErrorMessage((e as Error).message);
    } finally {
      setIsSyncing(false);
    }
  }

  async function runPipeline() {
    if (!activeProject) return;
    const projectId = activeProject.project_id;
    const effectiveRepoPath = repoPath.trim() || activeProject.repo_path;

    if (!uploadFile) {
      setErrorMessage("Please select a requirements document.");
      return;
    }
    if (activeProject.repo_type === "local" && !effectiveRepoPath) {
      setErrorMessage("Please enter a repository path.");
      return;
    }

    setErrorMessage("");
    setTraceMatrix(null);
    setSelectedRow(null);
    setActiveRunId(null);
    startTimer();

    try {
      setStep("resetting");
      setStepMessage("Resetting project data…");
      const resetRes = await fetch(`${API}/api/projects/${projectId}/reset`, { method: "POST" });
      if (!resetRes.ok) throw new Error("Reset failed");

      // Re-create the project record after reset
      const recreateRes = await fetch(`${API}/api/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: activeProject.name,
          description: activeProject.description,
          repo_type: activeProject.repo_type,
          repo_path: effectiveRepoPath,
          github_url: activeProject.github_url,
          branch: activeProject.branch,
        }),
      });
      if (!recreateRes.ok) {
        const err = await recreateRes.json().catch(() => ({}));
        if (recreateRes.status !== 409) throw new Error(err.detail || "Failed to recreate project");
      }

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

      setStep("ingesting");
      setStepMessage("Parsing repository & embedding code…");
      const ingestRes = await fetch(`${API}/api/projects/${projectId}/repo/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_path: effectiveRepoPath }),
      });
      if (!ingestRes.ok) {
        const err = await ingestRes.json().catch(() => ({}));
        throw new Error(err.detail || `Ingestion failed: HTTP ${ingestRes.status}`);
      }
      const ingestData = await ingestRes.json();
      setCodeCount(ingestData.persisted?.inserted_code_units || 0);

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

      const matrixRes = await fetch(`${API}/api/projects/${projectId}/trace-matrix`);
      if (matrixRes.ok) {
        setTraceMatrix(await matrixRes.json());
      }

      stopTimer();
      setStep("done");
      setStepMessage("Analysis complete!");
      fetchProjects();
    } catch (err) {
      stopTimer();
      setStep("error");
      setStepMessage("");
      setErrorMessage((err as Error).message);
    }
  }

  const isRunning = !["idle", "done", "error"].includes(step);


  async function loadProjectHistory(project: ProjectInfo) {
    setActiveProject(project);
    setRepoPath(project.repo_path || "");
    setView("analysis");
    setIsViewingHistory(true);
    setTraceMatrix(null);
    setActiveRunId(null);
    setStepMessage("Loading project data...");
    setStep("resetting");

    try {
      const res = await fetch(`${API}/api/projects/${project.project_id}/trace-matrix`);
      if (res.ok) {
        const data = await res.json();
        setTraceMatrix(data as TraceMatrixResponse);
        setStep("done");
        setStepMessage("Loaded historical run");
      } else {
        setStep("idle");
        setStepMessage("");
      }
    } catch {
      setStep("idle");
      setStepMessage("");
    }
  }

  function handleProjectCreated(project: ProjectInfo) {
    setActiveProject(project);
    setRepoPath(project.repo_path || "");
    setView("analysis");
    setIsViewingHistory(false);
    setTraceMatrix(null);
    setStep("idle");
    fetchProjects();
  }

  function goHome() {
    setView("landing");
    setTraceMatrix(null);
    setIsViewingHistory(false);
    setActiveProject(null);
    setStep("idle");
    setErrorMessage("");
    fetchProjects();
  }

  if (view === "create") {
    return <CreateProjectPage onCreated={handleProjectCreated} onCancel={goHome} />;
  }

  if (view === "landing") {
    return (
      <LandingPage
        projects={allProjects}
        onStartNew={() => setView("create")}
        onLoadProject={loadProjectHistory}
        onDeleteProject={handleDeleteProject}
        onDeleteAll={handleDeleteAll}
      />
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-6 py-10">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-3">
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
            <p className="text-xs text-foreground-muted flex items-center gap-2 mt-0.5">
              <span>{activeProject?.name || "Automated traceability"}</span>
              {activeProject?.repo_type === "github" && activeProject?.github_url && (
                <a
                  href={activeProject.github_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 rounded bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent hover:bg-accent/20 transition-all cursor-pointer"
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.385-1.335-1.755-1.335-1.755-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.605-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 21.795 24 17.295 24 12c0-6.63-5.37-12-12-12"/></svg>
                  GitHub
                </a>
              )}
              {activeProject?.last_commit_sha && (
                activeProject?.repo_type === "github" && activeProject?.github_url ? (
                  <a
                    href={`${activeProject.github_url.replace(/\.git$/, "")}/commit/${activeProject.last_commit_sha}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 rounded bg-surface-raised px-1.5 py-0.5 text-[10px] font-mono text-foreground-subtle hover:bg-surface-raised-hover transition-all cursor-pointer"
                  >
                    commit: {activeProject.last_commit_sha.slice(0, 7)}
                  </a>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded bg-surface-raised px-1.5 py-0.5 text-[10px] font-mono text-foreground-subtle">
                    commit: {activeProject.last_commit_sha.slice(0, 7)}
                  </span>
                )
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {activeProject?.repo_type === "github" && (traceMatrix || step === "done") && (
            <button
              onClick={handleSyncProject}
              disabled={isSyncing}
              className="flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/10 px-4 py-2 text-sm font-medium text-accent hover:bg-accent/20 transition-all disabled:opacity-50"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={isSyncing ? "animate-spin" : ""}>
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
              </svg>
              {isSyncing ? "Syncing..." : "Sync Latest"}
            </button>
          )}
          {traceMatrix && (
            <>
              <a
                href={`${API}/api/projects/${activeProject?.project_id}/runs/${activeRunId || 0}/export/csv`}
                download
                className="flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-raised/40 px-3.5 py-2 text-sm font-medium text-foreground-muted hover:bg-surface-raised hover:text-foreground transition-all cursor-pointer"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
                </svg>
                CSV
              </a>
              <a
                href={`${API}/api/projects/${activeProject?.project_id}/runs/${activeRunId || 0}/export/pdf`}
                download
                className="flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-raised/40 px-3.5 py-2 text-sm font-medium text-foreground-muted hover:bg-surface-raised hover:text-foreground transition-all cursor-pointer"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
                </svg>
                PDF
              </a>
            </>
          )}
          <button
            onClick={goHome}
            className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-foreground-muted hover:bg-surface-raised hover:text-foreground transition-all"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
            Back to Home
          </button>
        </div>
      </header>

      {!isViewingHistory && (
        <section className="rounded-2xl border border-border-subtle bg-surface p-6">
        <div className="grid gap-6 md:grid-cols-2">
          <FieldLabel label="Requirements Document">
            <input
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground file:mr-3 file:rounded-md file:border-0 file:bg-surface-raised file:px-3 file:py-1 file:text-xs file:font-medium file:text-foreground-muted focus:border-accent focus:ring-1 focus:ring-accent"
              type="file"
              accept=".txt,.md,.pdf,.docx"
              onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              disabled={isRunning}
            />
          </FieldLabel>

          {activeProject?.repo_type === "github" ? (
            <FieldLabel label="Code Repository (GitHub)">
              <div className="flex h-10 items-center rounded-lg border border-border bg-surface-raised px-3.5 py-2.5 text-sm text-foreground-muted font-mono select-none">
                {activeProject.github_url} ({activeProject.branch})
              </div>
            </FieldLabel>
          ) : (
            <FieldLabel label="Code Repository (local path)">
              <input
                className="w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm text-foreground focus:border-accent focus:ring-1 focus:ring-accent"
                value={repoPath}
                onChange={(e) => setRepoPath(e.target.value)}
                placeholder={activeProject?.repo_path || "/path/to/repository"}
                disabled={isRunning}
              />
            </FieldLabel>
          )}
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-4">
          <button
            className="rounded-xl bg-accent px-8 py-3 text-sm font-semibold text-white shadow-lg shadow-accent/20 transition-all hover:bg-accent-hover hover:shadow-accent/30 disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={runPipeline}
            disabled={isRunning}
          >
            {isRunning ? "Analyzing…" : "Analyze Traceability"}
          </button>

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

        {isRunning && <PipelineSteps currentStep={step} repoType={activeProject?.repo_type} />}
      </section>
      )}

      {(traceMatrix || step === "done") && (
        <div className="grid gap-4 sm:grid-cols-5 stagger-item">
          <StatCard
            label="Requirements"
            value={reqCount || traceMatrix?.requirements_total || 0}
            info="Functional requirements extracted from the uploaded document."
          />
          <StatCard
            label="Code Units"
            value={codeCount || activeProject?.code_units_count || 0}
            info="Code chunks (functions, classes, methods) parsed via tree-sitter."
          />
          <StatCard
            label="Trace Links"
            value={linkCount || activeProject?.trace_links_count || 0}
            info={`Requirement-to-code links generated (${reqCount || traceMatrix?.requirements_total || 0} × top-10).`}
          />
          {traceMatrix?.evaluation ? (
            <StatCard
              label="Model Accuracy"
              value={`${traceMatrix.evaluation.hit_at_k.toFixed(1)}%`}
              highlight
              info="Percentage of requirements with at least one correct match in the top 10 (Hit@10)."
            />
          ) : (
            <StatCard
              label="Trace Links"
              value={linkCount || activeProject?.trace_links_count || 0}
              info={`Requirement-to-code links generated (${reqCount || traceMatrix?.requirements_total || 0} × top-10).`}
            />
          )}
          <StatCard
            label={traceMatrix?.evaluation ? "Estimated Coverage" : "Estimated Coverage"}
            value={traceMatrix ? `${traceMatrix.completion_percentage.toFixed(1)}%` : "–"}
            highlight={!traceMatrix?.evaluation}
            info={traceMatrix?.evaluation
              ? "Confidence-based percentage of requirements with at least one predicted match above threshold."
              : `Requirements with estimated strong semantic match (similarity ≥ ${QUALITY_THRESHOLDS.MODERATE}).`
            }
          />
          <StatCard
            label="Avg Score"
            value={traceMatrix ? computeAvgScore(traceMatrix.rows) : "–"}
            info={`Mean best-match cosine similarity. ${QUALITY_THRESHOLDS.MODERATE}+ is strong, ${QUALITY_THRESHOLDS.STRONG}+ is excellent.`}
          />
        </div>
      )}

      {traceMatrix && traceMatrix.rows.length > 0 && (
        <div className="stagger-item">
          <CoverageDashboard matrix={traceMatrix} />
        </div>
      )}

      {syncMessage && (
        <div className="flex items-center gap-2 rounded-xl border border-accent/30 bg-accent/5 px-5 py-3 text-xs text-accent stagger-item">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
          <span>{syncMessage}</span>
        </div>
      )}

      {traceMatrix && traceMatrix.rows.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-4 stagger-item">
          <div className="lg:col-span-3">
            <section className="rounded-2xl border border-border-subtle bg-surface h-full">
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
                      {(() => {
                        const displayLinks = row.has_gold ? row.links.filter(l => l.is_correct) : row.links;
                        return displayLinks.length > 0 ? (
                          <div className="font-mono text-foreground-muted">
                            {displayLinks[0].file_path.split("/").pop()}
                            <span className="text-foreground-subtle">
                              :{displayLinks[0].start_line}
                            </span>
                          </div>
                        ) : (
                          <span className="text-foreground-subtle">—</span>
                        );
                      })()}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-foreground-muted">
                      {(() => {
                        const displayLinks = row.has_gold ? row.links.filter(l => l.is_correct) : row.links;
                        return displayLinks.length > 0 ? formatScore(displayLinks[0].score) : "—";
                      })()}
                    </td>
                    <td className="px-4 py-3">
                      <StatusPill label={row.is_correct_match ? "Implemented" : "Missing"} isBenchmark={row.has_gold} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
            </section>
          </div>

          <div className="lg:col-span-1">
            <RunHistoryTimeline
              runs={runs}
              activeRunId={activeRunId}
              onSelectRun={handleSelectRun}
            />
          </div>
        </div>
      )}

      {traceMatrix && traceMatrix.rows.length > 0 && activeProject && (
        <ImpactAnalysisSection
          matrix={traceMatrix}
          projectId={activeProject.project_id}
          runId={activeRunId}
        />
      )}

      <footer className="mt-auto border-t border-border-subtle pt-6 pb-4 text-center text-xs text-foreground-subtle">
        &copy; {new Date().getFullYear()} TraceAI. All rights reserved.
      </footer>

      {selectedRow && activeProject && (
        <DetailModal
          row={selectedRow}
          projectId={activeProject.project_id}
          runId={activeRunId}
          onClose={() => setSelectedRow(null)}
        />
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Create Project Page
// ---------------------------------------------------------------------------

function CreateProjectPage({ onCreated, onCancel }: { onCreated: (p: ProjectInfo) => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [repoType, setRepoType] = useState<"local" | "github">("local");
  const [repoPath, setRepoPath] = useState("");
  const [githubUrl, setGithubUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Project name is required");
      return;
    }
    setError("");
    setCreating(true);

    try {
      const res = await fetch(`${API}/api/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim(),
          repo_type: repoType,
          repo_path: repoType === "local" ? repoPath.trim() : "",
          github_url: repoType === "github" ? githubUrl.trim() : "",
          branch: repoType === "github" ? branch.trim() : "",
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Failed to create project: HTTP ${res.status}`);
      }
      const project = await res.json();
      onCreated(project);
    } catch (err) {
      setError((err as Error).message);
      setCreating(false);
    }
  }

  const gridStyle = {
    backgroundImage: `radial-gradient(var(--color-border) 1px, transparent 1px)`,
    backgroundSize: '24px 24px',
    backgroundPosition: '-12px -12px'
  };

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-start px-6 py-16 w-full bg-background overflow-hidden">
      <div className="absolute inset-0 z-0 opacity-[0.08]" style={gridStyle}></div>
      <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] rounded-full bg-accent-glow blur-3xl z-0 pointer-events-none"></div>

      <div className="relative z-10 w-full max-w-xl animate-fade-in">
        <button
          onClick={onCancel}
          className="flex items-center gap-2 mb-8 text-sm font-medium text-foreground-muted hover:text-foreground transition-colors"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
          Back to Home
        </button>

        <div className="rounded-2xl border border-border-subtle bg-surface p-8">
          <div className="flex items-center gap-3 mb-8">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent">
                <path d="M12 5v14M5 12h14" />
              </svg>
            </div>
            <h2 className="font-serif text-2xl tracking-tight">Create New Project</h2>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <FieldLabel label="Project Name *">
              <input
                className="w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm text-foreground focus:border-accent focus:ring-1 focus:ring-accent"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My iTrust Analysis"
                autoFocus
              />
            </FieldLabel>

            <FieldLabel label="Description">
              <textarea
                className="w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm text-foreground focus:border-accent focus:ring-1 focus:ring-accent resize-none"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Traceability analysis for the iTrust healthcare system"
                rows={2}
              />
            </FieldLabel>

            <FieldLabel label="Repository Source">
              <div className="flex gap-2">
                <button
                  type="button"
                  className={`flex-1 rounded-lg border px-4 py-2.5 text-sm font-medium transition-all ${
                    repoType === "local"
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-border bg-background text-foreground-muted hover:border-border hover:text-foreground"
                  }`}
                  onClick={() => setRepoType("local")}
                >
                  📁 Local Path
                </button>
                <button
                  type="button"
                  className={`flex-1 rounded-lg border px-4 py-2.5 text-sm font-medium transition-all ${
                    repoType === "github"
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-border bg-background text-foreground-muted hover:border-border hover:text-foreground"
                  }`}
                  onClick={() => setRepoType("github")}
                >
                  <span className="inline-flex items-center gap-1.5">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.385-1.335-1.755-1.335-1.755-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.605-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 21.795 24 17.295 24 12c0-6.63-5.37-12-12-12"/></svg>
                    GitHub
                  </span>
                </button>
              </div>
            </FieldLabel>

            {repoType === "local" && (
              <FieldLabel label="Repository Path">
                <input
                  className="w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm text-foreground font-mono focus:border-accent focus:ring-1 focus:ring-accent"
                  value={repoPath}
                  onChange={(e) => setRepoPath(e.target.value)}
                  placeholder="/Users/you/projects/my-repo"
                />
              </FieldLabel>
            )}

            {repoType === "github" && (
              <>
                <FieldLabel label="GitHub URL">
                  <input
                    className="w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm text-foreground font-mono focus:border-accent focus:ring-1 focus:ring-accent"
                    value={githubUrl}
                    onChange={(e) => setGithubUrl(e.target.value)}
                    placeholder="https://github.com/owner/repo"
                  />
                </FieldLabel>
                <FieldLabel label="Branch">
                  <input
                    className="w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm text-foreground focus:border-accent focus:ring-1 focus:ring-accent"
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    placeholder="main"
                  />
                </FieldLabel>
              </>
            )}

            {error && (
              <div className="text-sm text-error">{error}</div>
            )}

            <button
              type="submit"
              disabled={creating}
              className="mt-2 rounded-xl bg-accent px-8 py-3 text-sm font-semibold text-white shadow-lg shadow-accent/20 transition-all hover:bg-accent-hover hover:shadow-accent/30 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {creating ? "Creating…" : "Create & Start Analysis"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Landing Page
// ---------------------------------------------------------------------------

function LandingPage({
  projects,
  onStartNew,
  onLoadProject,
  onDeleteProject,
  onDeleteAll
}: {
  projects: ProjectInfo[],
  onStartNew: () => void,
  onLoadProject: (p: ProjectInfo) => void,
  onDeleteProject: (pid: string) => void,
  onDeleteAll: () => void
}) {
  const gridStyle = {
    backgroundImage: `radial-gradient(var(--color-border) 1px, transparent 1px)`,
    backgroundSize: '24px 24px',
    backgroundPosition: '-12px -12px'
  };

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-start px-6 py-24 w-full bg-background overflow-hidden">
      <div className="absolute inset-0 z-0 opacity-[0.15]" style={gridStyle}></div>
      <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] rounded-full bg-accent-glow blur-3xl z-0 pointer-events-none"></div>

      <div className="relative z-10 w-full max-w-5xl flex flex-col items-center text-center animate-fade-in">
        <div className="mx-auto flex h-24 w-24 items-center justify-center rounded-3xl bg-surface border border-border-subtle shadow-sm mb-10 animate-fade-in-delay-1">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-accent">
            <path d="M12 2L2 7l10 5 10-5-10-5Z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>
        <h1 className="font-serif text-6xl tracking-tight text-foreground sm:text-7xl mb-6 animate-fade-in-delay-2">
          Trace<span className="text-accent">AI</span>
        </h1>
        <p className="mx-auto max-w-2xl text-xl text-foreground-muted mb-12 animate-fade-in-delay-3 leading-relaxed">
          Intelligent requirements-to-code traceability. Connect your repository, upload your design documents, and establish high-confidence semantic trace links instantly.
        </p>

        <div className="flex flex-col sm:flex-row gap-4 mb-24 animate-fade-in-delay-4">
          <button
            onClick={onStartNew}
            className="rounded-full bg-accent px-10 py-4 text-lg font-medium text-white shadow-xl shadow-accent/20 transition-all hover:bg-accent-hover hover:shadow-accent/30 hover:-translate-y-1"
          >
            Start New Analysis
          </button>
        </div>

        {projects.length > 0 && (
          <div className="w-full text-left animate-fade-in-delay-4">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-4">
                <h3 className="text-xl font-serif tracking-tight text-foreground">Recent Analyses</h3>
                <span className="text-sm font-medium text-foreground-muted bg-surface-raised px-3 py-1 rounded-full">{projects.length} projects</span>
              </div>
              <button
                onClick={onDeleteAll}
                className="text-sm font-medium text-error/80 hover:text-error hover:bg-error/10 px-3 py-1.5 rounded-lg transition-colors flex items-center gap-2"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                Clear All
              </button>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {projects.map((p) => {
                const dateStr = p.last_run ? new Date(p.last_run).toLocaleDateString(undefined, {
                  month: 'short', day: 'numeric', year: 'numeric'
                }) : p.created_at ? new Date(p.created_at).toLocaleDateString(undefined, {
                  month: 'short', day: 'numeric', year: 'numeric'
                }) : "No runs yet";

                return (
                  <div
                    key={p.project_id}
                    role="button"
                    tabIndex={0}
                    onClick={() => onLoadProject(p)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onLoadProject(p);
                      }
                    }}
                    className="relative group flex flex-col items-start rounded-2xl border border-border-subtle bg-surface p-5 text-left transition-all hover:border-accent/40 hover:shadow-md hover:shadow-accent/5 hover:-translate-y-1 cursor-pointer"
                  >
                    <button
                      className="absolute top-4 right-4 p-2 text-foreground-muted hover:text-error hover:bg-error/10 rounded-full transition-colors opacity-0 group-hover:opacity-100 z-10"
                      onClick={(e) => { e.stopPropagation(); onDeleteProject(p.project_id); }}
                      title="Delete Project"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                    </button>
                    <div className="flex items-center gap-3 w-full mb-2 pr-8">
                      <div className="h-8 w-8 rounded-lg bg-accent/10 flex items-center justify-center text-accent group-hover:bg-accent group-hover:text-white transition-colors shrink-0">
                        {p.repo_type === "github" ? (
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.385-1.335-1.755-1.335-1.755-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.605-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 21.795 24 17.295 24 12c0-6.63-5.37-12-12-12"/></svg>
                        ) : (
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="font-semibold text-foreground truncate">{p.name}</div>
                        {p.description && (
                          <div className="text-xs text-foreground-muted truncate mt-0.5">{p.description}</div>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-foreground-muted mt-auto pt-3 border-t border-border-subtle/50 w-full">
                      <span className="flex items-center gap-1">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                        {dateStr}
                      </span>
                      {p.requirements_count > 0 && (
                        <span>{p.requirements_count} reqs</span>
                      )}
                      {p.trace_links_count > 0 && (
                        <span>{p.trace_links_count} links</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Shared Components
// ---------------------------------------------------------------------------

function PipelineSteps({ currentStep, repoType }: { currentStep: PipelineStep; repoType?: string }) {
  const steps: { key: PipelineStep; label: string }[] = [
    { key: "resetting", label: "Reset" },
    { key: "uploading", label: "Requirements" },
    { key: "ingesting", label: repoType === "github" ? "Clone & Analyze" : "Code Analysis" },
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

function DetailModal({
  row,
  projectId,
  runId,
  onClose,
}: {
  row: TraceMatrixRow;
  projectId: string;
  runId: number | null;
  onClose: () => void;
}) {
  const backdropRef = useRef<HTMLDivElement>(null);
  const isBenchmark = !!row.has_gold;
  const filteredLinks = isBenchmark ? row.links.filter(link => link.is_correct) : row.links;
  const bestLink = filteredLinks[0] || null;
  const [explanation, setExplanation] = useState<string>(bestLink?.explanation || "");
  const needsFetch = !!bestLink && (!bestLink.explanation || bestLink.explanation.startsWith("Semantic match between requirement"));
  const [loadingExp, setLoadingExp] = useState<boolean>(needsFetch);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", handleKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  useEffect(() => {
    if (!bestLink || !projectId) return;

    if (needsFetch) {
      const effectiveRunId = runId || 0;
      fetch(`${API}/api/projects/${projectId}/runs/${effectiveRunId}/requirements/${row.requirement_id}/explanation`)
        .then((res) => res.json())
        .then((data) => {
          if (data.explanation) {
            setExplanation(data.explanation);
            bestLink.explanation = data.explanation; // cache in memory
          }
        })
        .catch((err) => console.error("Failed to load explanation:", err))
        .finally(() => setLoadingExp(false));
    }
  }, [bestLink, projectId, runId, row.requirement_id, needsFetch]);

  const implPercent = Math.round(clampScore(row.best_score) * 100);
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
        <div className="flex items-center justify-between border-b border-border-subtle px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="rounded-lg bg-accent/10 px-3 py-1 text-sm font-semibold text-accent">
              {row.req_key}
            </span>
            <StatusPill label={row.best_label} />
          </div>
          <button
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-border-subtle text-foreground-muted hover:bg-surface-raised hover:text-foreground"
            onClick={onClose}
          >
            ×
          </button>
        </div>

        <div className="px-6 py-3 border-b border-border-subtle">
          <div className="flex items-center justify-between text-xs text-foreground-subtle mb-1.5">
            <span>Implementation Confidence</span>
            <span className="tabular-nums">{formatScore(row.best_score)}</span>
          </div>
          <div className="h-2 w-full rounded-full bg-surface-raised overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${progressColor}`}
              style={{ width: `${implPercent}%` }}
            />
          </div>
        </div>

        <div className="flex-1 overflow-auto">
          <div className="border-b border-border-subtle px-6 py-4">
            <div className="text-[10px] font-medium uppercase tracking-wider text-accent/70 mb-2">
              Requirement
            </div>
            <p className="text-sm leading-relaxed text-foreground">{row.text}</p>
          </div>

          {bestLink && (
            <div className="border-b border-border-subtle px-6 py-4 bg-surface-raised/40">
              <div className="text-[10px] font-medium uppercase tracking-wider text-accent/70 mb-2">
                Why This Matches
              </div>
              {loadingExp ? (
                <div className="flex items-center gap-2 text-xs text-foreground-muted italic">
                  <svg className="animate-spin h-3.5 w-3.5 text-accent" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Generating smart explanation via Gemini...
                </div>
              ) : (
                <p className="text-sm leading-relaxed text-foreground-muted italic">
                  &ldquo;{explanation}&rdquo;
                </p>
              )}
            </div>
          )}

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
                <SimpleHighlight code={bestLink.content} />
              </pre>
            </div>
          ) : (
            <div className="py-12 text-center text-sm text-foreground-subtle">
              No matching code found for this requirement.
            </div>
          )}

          {filteredLinks.length > 1 && (
            <div className="border-t border-border-subtle px-6 py-4">
              <div className="text-[10px] font-medium uppercase tracking-wider text-foreground-subtle/70 mb-3">
                {isBenchmark ? `All Verified Code (${filteredLinks.length} links)` : `All Matched Code (${filteredLinks.length} links)`}
              </div>
              <div className="space-y-1">
                {filteredLinks.map((link, i) => (
                  <div
                    key={link.code_unit_id}
                    className="flex items-center justify-between rounded-lg px-3 py-2 text-xs transition-colors hover:bg-surface-raised/60"
                  >
                    <div className="flex items-center gap-3">
                      <span className="w-5 text-right tabular-nums text-foreground-subtle">
                        {i + 1}
                      </span>
                      <span className="font-mono text-foreground-muted">
                        {link.file_path.split("/").pop()}
                        <span className="text-foreground-subtle">:{link.start_line}</span>
                      </span>
                      <span className="text-foreground-subtle">{link.symbol}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="tabular-nums text-foreground-muted">
                        {formatScore(link.score)}
                      </span>
                      <StatusPill label={link.label as TraceLabel} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusPill({ label, isBenchmark }: { label: string; isBenchmark?: boolean }) {
  let displayLabel = label;
  let cls = "";
  
  if (isBenchmark) {
    if (label === "Implemented") {
      displayLabel = "Hit";
      cls = "bg-emerald-500/15 text-emerald-300";
    } else {
      displayLabel = "Miss";
      cls = "bg-red-500/15 text-red-300";
    }
  } else {
    cls =
      label === "Implemented"
        ? "bg-emerald-500/15 text-emerald-300"
        : label === "Partial"
          ? "bg-amber-500/15 text-amber-300"
          : "bg-red-500/15 text-red-300";
  }
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>{displayLabel}</span>;
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

function SimpleHighlight({ code }: { code: string }) {
  if (!code) return <span>Code content not available.</span>;

  const rules = [
    { regex: /^("""[\s\S]*?"""|'''[\s\S]*?''')/, color: 'text-emerald-400' },
    { regex: /^(".*?"|'.*?'|`.*?`)/, color: 'text-emerald-400' },
    { regex: /^(#.*|\/\/.*)/, color: 'text-foreground-subtle' },
    { regex: /^(def|class|return|import|from|if|else|elif|for|while|try|except|with|as|pass|async|await|function|const|let|var|interface|type|export|default|null|true|false|None|True|False)\b/, color: 'text-fuchsia-400' },
    { regex: /^([a-zA-Z_]\w*)(?=\s*\()/, color: 'text-blue-400' },
    { regex: /^([A-Z][a-zA-Z0-9_]*)\b/, color: 'text-amber-200' },
    { regex: /^(\b\d+(\.\d+)?\b)/, color: 'text-amber-400' },
    { regex: /^(@[a-zA-Z_]\w*)/, color: 'text-fuchsia-300' },
    { regex: /^([a-zA-Z_]\w*)/, color: 'text-foreground' },
    { regex: /^(\s+)/, color: '' },
    { regex: /^(.)/, color: 'text-foreground-muted' },
  ];

  let html = "";
  let current = code;

  while (current.length > 0) {
    let matched = false;
    for (const rule of rules) {
      const match = current.match(rule.regex);
      if (match) {
        const text = match[0]
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;");

        if (rule.color) {
          html += `<span class="${rule.color}">${text}</span>`;
        } else {
          html += text;
        }
        current = current.slice(match[0].length);
        matched = true;
        break;
      }
    }
    if (!matched) {
      html += current[0]
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      current = current.slice(1);
    }
  }

  return <code dangerouslySetInnerHTML={{ __html: html }} />;
}

function CoverageDashboard({ matrix }: { matrix: TraceMatrixResponse }) {
  const total = matrix.requirements_total;
  const rows = matrix.rows || [];
  const evalData = matrix.evaluation;

  if (evalData) {
    // Benchmark Mode: Calculate metrics based on gold-annotated requirements only
    const totalEvaluated = rows.filter(r => r.has_gold).length;
    const hits = rows.filter(r => r.is_correct_match).length;
    const misses = totalEvaluated - hits;
    const unevaluated = total - totalEvaluated;
    
    const pctHits = totalEvaluated > 0 ? (hits / totalEvaluated) * 100 : 0;
    const pctMisses = totalEvaluated > 0 ? (misses / totalEvaluated) * 100 : 0;

    return (
      <div className="grid gap-6 md:grid-cols-2 rounded-2xl border border-border-subtle bg-surface p-6 mb-6">
        {/* Left Column: Traceability Health Bar */}
        <div className="flex flex-col justify-center space-y-4">
          <div>
            <h4 className="text-sm font-semibold text-foreground mb-1">Benchmark Model Accuracy</h4>
            <p className="text-xs text-foreground-subtle">Ground-truth verification against {totalEvaluated} gold-annotated requirements ({unevaluated} unlabeled/skipped).</p>
          </div>

          {/* Stacked Progress Bar */}
          <div className="h-4 w-full rounded-full bg-surface-raised flex overflow-hidden border border-border-subtle">
            {pctHits > 0 && (
              <div
                style={{ width: `${pctHits}%` }}
                className="h-full bg-emerald-500 transition-all duration-500 hover:brightness-110"
                title={`Hits: ${hits} (${pctHits.toFixed(1)}%)`}
              />
            )}
            {pctMisses > 0 && (
              <div
                style={{ width: `${pctMisses}%` }}
                className="h-full bg-red-500 transition-all duration-500 hover:brightness-110"
                title={`Misses: ${misses} (${pctMisses.toFixed(1)}%)`}
              />
            )}
          </div>

          {/* Legend */}
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="flex flex-col gap-0.5 rounded-lg bg-emerald-500/5 border border-emerald-500/10 p-2.5">
              <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider">Gold Hits</span>
              <span className="text-base font-serif font-bold text-foreground">{hits}</span>
              <span className="text-[10px] text-foreground-subtle">{pctHits.toFixed(1)}% of evaluated</span>
            </div>
            <div className="flex flex-col gap-0.5 rounded-lg bg-red-500/5 border border-red-500/10 p-2.5">
              <span className="text-[10px] font-bold text-red-400 uppercase tracking-wider">Misses</span>
              <span className="text-base font-serif font-bold text-foreground">{misses}</span>
              <span className="text-[10px] text-foreground-subtle">{pctMisses.toFixed(1)}% of evaluated</span>
            </div>
            <div className="flex flex-col gap-0.5 rounded-lg bg-blue-500/5 border border-blue-500/10 p-2.5">
              <span className="text-[10px] font-bold text-blue-400 uppercase tracking-wider">Self-Confidence</span>
              <span className="text-base font-serif font-bold text-foreground">{matrix.requirements_implemented}</span>
              <span className="text-[10px] text-foreground-subtle">{matrix.completion_percentage.toFixed(1)}% estimated</span>
            </div>
          </div>
        </div>

        {/* Right Column: Benchmark Metrics Breakdown */}
        <div className="flex flex-col justify-center space-y-4">
          <div>
            <h4 className="text-sm font-semibold text-foreground mb-1">Retrieval Metrics Breakdown</h4>
            <p className="text-xs text-foreground-subtle">Standard evaluation measures of model ranking and recall.</p>
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="rounded-xl border border-border-subtle bg-surface-raised p-3">
              <div className="text-[10px] font-bold text-foreground-muted uppercase tracking-wider">MRR</div>
              <div className="text-lg font-serif font-bold text-foreground tabular-nums">{evalData.mrr.toFixed(3)}</div>
              <div className="text-[9px] text-foreground-subtle mt-0.5">Mean Reciprocal Rank</div>
            </div>
            <div className="rounded-xl border border-border-subtle bg-surface-raised p-3">
              <div className="text-[10px] font-bold text-foreground-muted uppercase tracking-wider">nDCG@10</div>
              <div className="text-lg font-serif font-bold text-foreground tabular-nums">{evalData.ndcg_at_k.toFixed(3)}</div>
              <div className="text-[9px] text-foreground-subtle mt-0.5">Normalized Discounted Cumulative Gain</div>
            </div>
            <div className="rounded-xl border border-border-subtle bg-surface-raised p-3">
              <div className="text-[10px] font-bold text-foreground-muted uppercase tracking-wider">MAP</div>
              <div className="text-lg font-serif font-bold text-foreground tabular-nums">{evalData.map_score.toFixed(3)}</div>
              <div className="text-[9px] text-foreground-subtle mt-0.5">Mean Average Precision</div>
            </div>
            <div className="rounded-xl border border-border-subtle bg-surface-raised p-3">
              <div className="text-[10px] font-bold text-foreground-muted uppercase tracking-wider">Precision / Recall</div>
              <div className="text-lg font-serif font-bold text-foreground tabular-nums">
                {evalData.precision_at_k.toFixed(3)} / {evalData.recall_at_k.toFixed(3)}
              </div>
              <div className="text-[9px] text-foreground-subtle mt-0.5">P@10 / R@10 ratio</div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Fallback Confidence mode (No gold standard)
  const { implemented, partial, missing } = computeCoverageCounts(rows);

  const pctImpl = total > 0 ? (implemented / total) * 100 : 0;
  const pctPart = total > 0 ? (partial / total) * 100 : 0;
  const pctMiss = total > 0 ? (missing / total) * 100 : 0;

  const { strongMatch, moderateMatch, weakMatch, noMatch } = computeQualityBuckets(rows);
  const maxCount = Math.max(strongMatch, moderateMatch, weakMatch, noMatch, 1);

  return (
    <div className="grid gap-6 md:grid-cols-2 rounded-2xl border border-border-subtle bg-surface p-6 mb-6">
      {/* Left Column: Traceability Health Bar */}
      <div className="flex flex-col justify-center space-y-4">
        <div>
          <h4 className="text-sm font-semibold text-foreground mb-1">Traceability Coverage</h4>
          <p className="text-xs text-foreground-subtle">Requirement mapping coverage and status summary.</p>
        </div>

        {/* Stacked Progress Bar */}
        <div className="h-4 w-full rounded-full bg-surface-raised flex overflow-hidden border border-border-subtle">
          {pctImpl > 0 && (
            <div
              style={{ width: `${pctImpl}%` }}
              className="h-full bg-emerald-500 transition-all duration-500 hover:brightness-110"
              title={`Implemented: ${implemented} (${pctImpl.toFixed(1)}%)`}
            />
          )}
          {pctPart > 0 && (
            <div
              style={{ width: `${pctPart}%` }}
              className="h-full bg-amber-500 transition-all duration-500 hover:brightness-110"
              title={`Partial: ${partial} (${pctPart.toFixed(1)}%)`}
            />
          )}
          {pctMiss > 0 && (
            <div
              style={{ width: `${pctMiss}%` }}
              className="h-full bg-red-500 transition-all duration-500 hover:brightness-110"
              title={`Missing: ${missing} (${pctMiss.toFixed(1)}%)`}
            />
          )}
        </div>

        {/* Legend */}
        <div className="grid grid-cols-3 gap-2 text-xs">
          <div className="flex flex-col gap-0.5 rounded-lg bg-emerald-500/5 border border-emerald-500/10 p-2.5">
            <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider">Implemented</span>
            <span className="text-base font-serif font-bold text-foreground">{implemented}</span>
            <span className="text-[10px] text-foreground-subtle">{pctImpl.toFixed(1)}% of total</span>
          </div>
          <div className="flex flex-col gap-0.5 rounded-lg bg-amber-500/5 border border-amber-500/10 p-2.5">
            <span className="text-[10px] font-bold text-amber-400 uppercase tracking-wider">Partial</span>
            <span className="text-base font-serif font-bold text-foreground">{partial}</span>
            <span className="text-[10px] text-foreground-subtle">{pctPart.toFixed(1)}% of total</span>
          </div>
          <div className="flex flex-col gap-0.5 rounded-lg bg-red-500/5 border border-red-500/10 p-2.5">
            <span className="text-[10px] font-bold text-red-400 uppercase tracking-wider">Missing</span>
            <span className="text-base font-serif font-bold text-foreground">{missing}</span>
            <span className="text-[10px] text-foreground-subtle">{pctMiss.toFixed(1)}% of total</span>
          </div>
        </div>
      </div>

      {/* Right Column: Trace Quality Distribution */}
      <div className="flex flex-col justify-center space-y-4">
        <div>
          <h4 className="text-sm font-semibold text-foreground mb-1">Mapping Quality Breakdown</h4>
          <p className="text-xs text-foreground-subtle">Confidence validation level of requirements-to-code trace links.</p>
        </div>

        <div className="space-y-2">
          {/* High Certainty */}
          <div className="flex items-center gap-3 text-xs">
            <div className="w-32 text-foreground-muted shrink-0 flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              <span>Strong Match (≥ {QUALITY_THRESHOLDS.STRONG})</span>
            </div>
            <div className="h-3 flex-1 rounded bg-surface-raised overflow-hidden">
              <div
                style={{ width: `${(strongMatch / maxCount) * 100}%` }}
                className="h-full bg-emerald-500/80 transition-all duration-500"
              />
            </div>
            <span className="w-6 text-right font-medium text-foreground tabular-nums">{strongMatch}</span>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <div className="w-32 text-foreground-muted shrink-0 flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-blue-500" />
              <span>Moderate ({QUALITY_THRESHOLDS.MODERATE} – {QUALITY_THRESHOLDS.STRONG})</span>
            </div>
            <div className="h-3 flex-1 rounded bg-surface-raised overflow-hidden">
              <div
                style={{ width: `${(moderateMatch / maxCount) * 100}%` }}
                className="h-full bg-blue-500/80 transition-all duration-500"
              />
            </div>
            <span className="w-6 text-right font-medium text-foreground tabular-nums">{moderateMatch}</span>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <div className="w-32 text-foreground-muted shrink-0 flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-amber-500" />
              <span>Weak Match ({QUALITY_THRESHOLDS.WEAK} – {QUALITY_THRESHOLDS.MODERATE})</span>
            </div>
            <div className="h-3 flex-1 rounded bg-surface-raised overflow-hidden">
              <div
                style={{ width: `${(weakMatch / maxCount) * 100}%` }}
                className="h-full bg-amber-500/80 transition-all duration-500"
              />
            </div>
            <span className="w-6 text-right font-medium text-foreground tabular-nums">{weakMatch}</span>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <div className="w-32 text-foreground-muted shrink-0 flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-red-500" />
              <span>No Match (&lt; {QUALITY_THRESHOLDS.WEAK})</span>
            </div>
            <div className="h-3 flex-1 rounded bg-surface-raised overflow-hidden">
              <div
                style={{ width: `${(noMatch / maxCount) * 100}%` }}
                className="h-full bg-red-500/80 transition-all duration-500"
              />
            </div>
            <span className="w-6 text-right font-medium text-foreground tabular-nums">{noMatch}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

type ImpactResult = {
  file_path: string;
  affected_requirements: {
    requirement_id: string;
    req_key: string;
    text: string;
    score: number;
    label: string;
    code_key: string;
  }[];
  risk_level: "high" | "medium" | "low";
  affected_count: number;
};

function ImpactAnalysisSection({
  matrix,
  projectId,
  runId,
}: {
  matrix: TraceMatrixResponse;
  projectId: string;
  runId: number | null;
}) {
  const [selectedFile, setSelectedFile] = useState<string>("");
  const [impact, setImpact] = useState<ImpactResult | null>(null);
  const [loading, setLoading] = useState(false);

  const uniqueFiles = Array.from(
    new Set(
      matrix.rows
        .flatMap((r) => r.links.map((l) => l.file_path))
        .filter(Boolean)
    )
  ).sort();

  function fetchImpact(filePath: string) {
    setSelectedFile(filePath);
    if (!filePath || !projectId) {
      setImpact(null);
      return;
    }
    setLoading(true);
    const effectiveRunId = runId || 0;
    fetch(
      `${API}/api/projects/${projectId}/impact?file_path=${encodeURIComponent(filePath)}&run_id=${effectiveRunId}`
    )
      .then((res) => res.json())
      .then((data: ImpactResult) => setImpact(data))
      .catch((err) => console.error("Impact analysis failed:", err))
      .finally(() => setLoading(false));
  }

  const riskColors = {
    high: { bg: "bg-red-500/10", border: "border-red-500/20", text: "text-red-400", icon: "🔴" },
    medium: { bg: "bg-amber-500/10", border: "border-amber-500/20", text: "text-amber-400", icon: "🟡" },
    low: { bg: "bg-emerald-500/10", border: "border-emerald-500/20", text: "text-emerald-400", icon: "🟢" },
  };

  return (
    <section className="rounded-2xl border border-border-subtle bg-surface p-5 stagger-item">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
        <div>
          <h3 className="font-serif text-lg">Impact Analysis</h3>
          <p className="text-xs text-foreground-subtle mt-0.5">
            Select a file to see which requirements it affects.
          </p>
        </div>
        <select
          value={selectedFile}
          onChange={(e) => fetchImpact(e.target.value)}
          className="rounded-lg border border-border-subtle bg-surface-raised px-3 py-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-accent max-w-xs"
        >
          <option value="">Choose a file…</option>
          {uniqueFiles.map((fp) => (
            <option key={fp} value={fp}>
              {fp}
            </option>
          ))}
        </select>
      </div>

      {loading && (
        <div className="text-xs text-foreground-subtle py-4 text-center animate-pulse">
          Analyzing impact…
        </div>
      )}

      {!loading && impact && (
        <div className="space-y-4">
          {/* Risk Level Banner */}
          <div
            className={`flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-medium border ${riskColors[impact.risk_level].bg} ${riskColors[impact.risk_level].border}`}
          >
            <span>{riskColors[impact.risk_level].icon}</span>
            <span className={riskColors[impact.risk_level].text}>
              {impact.risk_level.toUpperCase()} RISK
            </span>
            <span className="text-foreground-muted">
              — {impact.affected_count} requirement{impact.affected_count !== 1 ? "s" : ""} affected
            </span>
          </div>

          {/* Affected Requirements List */}
          {impact.affected_requirements.length > 0 && (
            <div className="overflow-auto rounded-xl border border-border-subtle" style={{ maxHeight: "280px" }}>
              <table className="min-w-full text-xs">
                <thead className="sticky top-0 bg-surface z-10">
                  <tr className="border-b border-border-subtle text-left text-[10px] uppercase tracking-wide text-foreground-subtle">
                    <th className="px-3 py-2">Requirement</th>
                    <th className="px-3 py-2">Description</th>
                    <th className="px-3 py-2 text-right">Score</th>
                    <th className="px-3 py-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {impact.affected_requirements.map((req) => (
                    <tr
                      key={req.requirement_id}
                      className="border-b border-border-subtle/50 transition-colors hover:bg-surface-raised/50"
                    >
                      <td className="px-3 py-2 font-medium text-foreground whitespace-nowrap">
                        {req.req_key}
                      </td>
                      <td className="px-3 py-2 text-foreground-muted max-w-sm truncate">
                        {req.text}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-foreground-muted">
                        {formatScore(req.score)}
                      </td>
                      <td className="px-3 py-2">
                        <StatusPill label={req.label as TraceLabel} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {!loading && !impact && selectedFile === "" && (
        <div className="text-xs text-foreground-subtle py-6 text-center">
          Select a file from the dropdown above to run impact analysis.
        </div>
      )}
    </section>
  );
}

function RunHistoryTimeline({
  runs,
  activeRunId,
  onSelectRun,
}: {
  runs: AnalysisRun[];
  activeRunId: number | null;
  onSelectRun: (runId: number) => void;
}) {
  return (
    <section className="rounded-2xl border border-border-subtle bg-surface p-5 h-full">
      <h3 className="font-serif text-lg mb-4">Run History</h3>
      {runs.length === 0 ? (
        <div className="text-xs text-foreground-subtle py-4">No runs recorded yet.</div>
      ) : (
        <div className="relative border-l border-border-subtle pl-4 ml-2 space-y-5">
          {runs.map((r, i) => {
            const date = new Date(r.created_at).toLocaleDateString(undefined, {
              month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
            });
            const changedFiles = JSON.parse(r.changed_files || "[]");
            const isActive = activeRunId === r.id || (activeRunId === null && i === 0);

            return (
              <div
                key={r.id}
                onClick={() => onSelectRun(r.id)}
                className={`relative cursor-pointer p-2.5 rounded-xl border transition-all ${
                  isActive
                    ? "bg-accent/5 border-accent/25 text-foreground"
                    : "border-transparent hover:bg-surface-raised/40 text-foreground-muted"
                }`}
              >
                <span className={`absolute left-[-21px] top-4.5 h-2 w-2 rounded-full border border-surface ${isActive ? "bg-accent" : "bg-foreground-subtle"}`} />
                <div className="text-xs font-semibold text-foreground">{date}</div>
                {r.commit_sha && (
                  <div className="text-[10px] font-mono text-accent mt-0.5">
                    commit: {r.commit_sha.slice(0, 7)}
                  </div>
                )}
                <div className="text-[10px] text-foreground-muted mt-1 space-y-0.5">
                  <div>{r.requirements_count} reqs · {r.code_units_count} chunks · {r.trace_links_count} links</div>
                  {changedFiles.length > 0 && (
                    <div className="text-foreground-subtle truncate max-w-full" title={changedFiles.join(", ")}>
                      Modified: {changedFiles.length} file{changedFiles.length === 1 ? "" : "s"}
                    </div>
                  )}
                  <div className="text-foreground-subtle">Duration: {r.execution_time_seconds}s</div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
