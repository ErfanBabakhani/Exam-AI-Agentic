"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, getErrorMessage, isBackgroundNetworkError, type GradingRunDetail, type GradingRunSummary, type TokenResponse, type User } from "@/lib/api";
import { clearAccessToken, hasAccessToken, persistAccessToken } from "@/lib/auth";
import { getReusableRecentFile, listRecentFiles, rememberRecentFile, type RecentFileEntry } from "@/lib/recent-files";
import { AppShell } from "@/components/app-shell";
import { AppTopbar } from "@/components/app-topbar";
import { AuthForm } from "@/components/auth-form";
import { ErrorAlert } from "@/components/error-alert";
import { FileUploadCard } from "@/components/file-upload-card";
import { GradingHistory } from "@/components/grading-history";
import { GradingProgressCard } from "@/components/grading-progress-card";
import { GradingResult } from "@/components/grading-result";
import { LoadingState } from "@/components/loading-state";
import { Sidebar } from "@/components/sidebar";
import { StatusBadge } from "@/components/status-badge";
import { TransientMessage } from "@/components/transient-message";
import { WelcomePanel } from "@/components/welcome-panel";
import { downloadPdfExport, exportRunsAsCsv, exportRunsAsText } from "@/lib/history-export";


type SessionStatus = "checking" | "authenticated" | "unauthenticated";
type UploadMode = "single" | "batch";

function isTerminalStatus(status: string) {
  return status === "completed" || status === "failed" || status === "canceled";
}

export function DashboardPage() {
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>("checking");
  const [user, setUser] = useState<User | null>(null);
  const [runs, setRuns] = useState<GradingRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<GradingRunDetail | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [uploadMode, setUploadMode] = useState<UploadMode>("single");
  const [examPdf, setExamPdf] = useState<File | null>(null);
  const [studentPdf, setStudentPdf] = useState<File | null>(null);
  const [studentBatchPdfs, setStudentBatchPdfs] = useState<File[]>([]);
  const [recentExamFiles, setRecentExamFiles] = useState<RecentFileEntry[]>([]);
  const [recentStudentFiles, setRecentStudentFiles] = useState<RecentFileEntry[]>([]);
  const [batchRunIds, setBatchRunIds] = useState<string[]>([]);
  const [uploadResetKey, setUploadResetKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [cancelBusyId, setCancelBusyId] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function loadDashboard(preferredRunId?: string) {
    const [currentUser, gradingRuns] = await Promise.all([api.me(), api.listGradings()]);
    setUser(currentUser);
    setRuns(gradingRuns);

    const runIdToLoad = preferredRunId ?? gradingRuns[0]?.id;
    if (!runIdToLoad) {
      setSelectedRun(null);
      return;
    }
    setSelectedRun(await api.getGrading(runIdToLoad));
  }

  async function bootstrap() {
    if (!hasAccessToken()) {
      setSessionStatus("unauthenticated");
      setUser(null);
      setRuns([]);
      setSelectedRun(null);
      return;
    }

    setSessionStatus("checking");
    try {
      await loadDashboard();
      setSessionStatus("authenticated");
    } catch (loadError) {
      setError(getErrorMessage(loadError));
      setSuccess("");
      if (!hasAccessToken()) {
        setSessionStatus("unauthenticated");
        setUser(null);
        setRuns([]);
        setSelectedRun(null);
      } else {
        setSessionStatus("authenticated");
      }
    }
  }

  useEffect(() => {
    void bootstrap();
    setRecentExamFiles(listRecentFiles("exam"));
    setRecentStudentFiles(listRecentFiles("student"));
  }, []);

  useEffect(() => {
    if (!activeRunId) {
      return;
    }

    let cancelled = false;
    const poll = window.setInterval(async () => {
      try {
        const statusPayload = await api.getGradingStatus(activeRunId);
        if (cancelled) {
          return;
        }
        setSelectedRun((current) =>
          current && current.id === activeRunId
            ? { ...current, ...statusPayload }
            : current
        );
        setRuns((currentRuns) =>
          currentRuns.map((run) => (run.id === activeRunId ? { ...run, ...statusPayload } : run))
        );

        if (isTerminalStatus(statusPayload.status)) {
          window.clearInterval(poll);
          setActiveRunId(null);
          await loadDashboard(activeRunId);
          if (statusPayload.status === "completed") {
            setSuccess("Grading finished and was saved.");
          } else if (statusPayload.status === "canceled") {
            setSuccess("Grading was canceled.");
          } else if (statusPayload.error_message) {
            setError(statusPayload.error_message);
          }
        }
      } catch (pollError) {
        if (cancelled) {
          return;
        }
        if (!hasAccessToken()) {
          setSessionStatus("unauthenticated");
          setUser(null);
          setRuns([]);
          setSelectedRun(null);
          setActiveRunId(null);
          return;
        }
        if (!isBackgroundNetworkError(pollError)) {
          setError(getErrorMessage(pollError));
        }
      }
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(poll);
    };
  }, [activeRunId]);

  useEffect(() => {
    if (sessionStatus !== "authenticated") {
      return;
    }

    const trackedBatchRunIds = runs
      .filter((run) => batchRunIds.includes(run.id) && !isTerminalStatus(run.status))
      .map((run) => run.id);
    if (trackedBatchRunIds.length === 0) {
      return;
    }

    let cancelled = false;
    const poll = window.setInterval(async () => {
      try {
        const statusPayloads = await Promise.all(trackedBatchRunIds.map((runId) => api.getGradingStatus(runId)));
        if (cancelled) {
          return;
        }

        const payloadMap = new Map(statusPayloads.map((payload) => [payload.id, payload]));
        setRuns((currentRuns) =>
          currentRuns.map((run) => {
            const payload = payloadMap.get(run.id);
            return payload ? { ...run, ...payload } : run;
          })
        );
        setSelectedRun((current) => (current ? { ...current, ...(payloadMap.get(current.id) ?? {}) } : current));

        const hasTerminalUpdate = statusPayloads.some((payload) => isTerminalStatus(payload.status));
        if (hasTerminalUpdate) {
          await loadDashboard(selectedRun?.id);
        }
      } catch (pollError) {
        if (cancelled) {
          return;
        }
        if (!hasAccessToken()) {
          setSessionStatus("unauthenticated");
          setUser(null);
          setRuns([]);
          setSelectedRun(null);
          setActiveRunId(null);
          return;
        }
        if (!isBackgroundNetworkError(pollError)) {
          setError(getErrorMessage(pollError));
        }
      }
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(poll);
    };
  }, [batchRunIds, runs, selectedRun?.id, sessionStatus]);

  useEffect(() => {
    if (sessionStatus !== "authenticated") {
      return;
    }

    let cancelled = false;
    async function refreshDashboard() {
      try {
        const gradingRuns = await api.listGradings();
        if (cancelled) {
          return;
        }
        setRuns(gradingRuns);
        const selectedId = selectedRun?.id ?? gradingRuns[0]?.id;
        if (selectedId) {
          setSelectedRun(await api.getGrading(selectedId));
        }
      } catch (pollError) {
        if (cancelled) {
          return;
        }
        if (!hasAccessToken()) {
          setSessionStatus("unauthenticated");
          setUser(null);
          setRuns([]);
          setSelectedRun(null);
          return;
        }
        if (!isBackgroundNetworkError(pollError)) {
          setError(getErrorMessage(pollError));
        }
      }
    }

    const poll = window.setInterval(() => {
      void refreshDashboard();
    }, 5000);

    function handleFocus() {
      void refreshDashboard();
    }

    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleFocus);

    return () => {
      cancelled = true;
      window.clearInterval(poll);
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleFocus);
    };
  }, [selectedRun?.id, sessionStatus]);

  async function handleAuthenticated(token: TokenResponse, message: string) {
    persistAccessToken(token.access_token);
    setError("");
    setSuccess(message);
    await bootstrap();
  }

  function rememberSelections(exam: File | null, students: File[]) {
    if (exam) {
      rememberRecentFile("exam", exam);
      setRecentExamFiles(listRecentFiles("exam"));
    }
    if (students.length > 0) {
      for (const student of students) {
        rememberRecentFile("student", student);
      }
      setRecentStudentFiles(listRecentFiles("student"));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || isGradingInFlight) {
      return;
    }
    if (!examPdf || (uploadMode === "single" && !studentPdf) || (uploadMode === "batch" && studentBatchPdfs.length === 0)) {
      setError(uploadMode === "batch" ? "Choose one exam PDF and at least one student PDF." : "Choose both PDFs before submitting a grading run.");
      setSuccess("");
      return;
    }

    setBusy(true);
    setError("");
    setSuccess("");
    try {
      if (uploadMode === "batch") {
        const response = await api.submitBatchGrading({ examPdf, studentPdfs: studentBatchPdfs });
        const firstRun = response.runs[0] ?? null;
        if (firstRun) {
          setSelectedRun(firstRun);
          setActiveRunId(firstRun.id);
        }
        setBatchRunIds(response.runs.map((run) => run.id));
        rememberSelections(examPdf, studentBatchPdfs);
        await loadDashboard(firstRun?.id);
        setSuccess(`Queued ${response.queue_size} grading runs. The queue will update as each submission completes.`);
      } else {
        const created = await api.submitGrading({ examPdf, studentPdf: studentPdf! });
        setSelectedRun(created);
        setActiveRunId(created.id);
        rememberSelections(examPdf, [studentPdf!]);
        await loadDashboard(created.id);
        setSuccess("Grading started. The dashboard will keep updating while the run is processing.");
      }
      setExamPdf(null);
      setStudentPdf(null);
      setStudentBatchPdfs([]);
      setUploadResetKey((value) => value + 1);
    } catch (submissionError) {
      setError(getErrorMessage(submissionError));
    } finally {
      setBusy(false);
      setSessionStatus(hasAccessToken() ? "authenticated" : "unauthenticated");
    }
  }

  function handleModeChange(mode: UploadMode) {
    setUploadMode(mode);
    setStudentPdf(null);
    setStudentBatchPdfs([]);
    setError("");
  }

  function reuseRecentExam(entryId: string) {
    const file = getReusableRecentFile(entryId);
    if (!file) {
      setError("That recent exam file is not reusable after refresh. Select it again from disk.");
      return;
    }
    setExamPdf(file);
  }

  function reuseRecentStudent(entryId: string) {
    const file = getReusableRecentFile(entryId);
    if (!file) {
      setError("That recent student file is not reusable after refresh. Select it again from disk.");
      return;
    }
    if (uploadMode === "batch") {
      setStudentBatchPdfs((current) => {
        const exists = current.some((item) => item.name === file.name && item.size === file.size);
        return exists ? current : [...current, file];
      });
      return;
    }
    setStudentPdf(file);
  }

  async function handleExportSelected(runIds: string[], format: "csv" | "txt" | "pdf") {
    if (runIds.length === 0) {
      return;
    }

    setExportBusy(true);
    setError("");
    try {
      if (format === "csv") {
        const details = await Promise.all(runIds.map((runId) => api.getGrading(runId)));
        exportRunsAsCsv(details);
      } else if (format === "txt") {
        const details = await Promise.all(runIds.map((runId) => api.getGrading(runId)));
        exportRunsAsText(details);
      } else {
        const { blob, fileName } = await api.exportGradingsPdf(runIds);
        downloadPdfExport(blob, fileName ?? `grading-runs-${runIds.length}.pdf`);
      }
      setSuccess(`Exported ${runIds.length} grading run${runIds.length === 1 ? "" : "s"} as ${format.toUpperCase()}.`);
    } catch (exportError) {
      setError(getErrorMessage(exportError));
    } finally {
      setExportBusy(false);
    }
  }

  async function handleDeleteSelected(runIds: string[]) {
    if (runIds.length === 0) {
      return;
    }

    const confirmed = window.confirm(
      `Remove ${runIds.length} grading run${runIds.length === 1 ? "" : "s"}? This cannot be undone.`
    );
    if (!confirmed) {
      return;
    }

    setDeleteBusy(true);
    setError("");
    setSuccess("");
    try {
      const payload = await api.deleteGradings(runIds);
      const nextSelectedRunId =
        selectedRun && !payload.deleted_ids.includes(selectedRun.id) ? selectedRun.id : undefined;
      await loadDashboard(nextSelectedRunId);
      setBatchRunIds((current) => current.filter((runId) => !payload.deleted_ids.includes(runId)));
      if (activeRunId && payload.deleted_ids.includes(activeRunId)) {
        setActiveRunId(null);
      }
      setSuccess(`Removed ${payload.deleted_count} grading run${payload.deleted_count === 1 ? "" : "s"}.`);
    } catch (deleteError) {
      setError(getErrorMessage(deleteError));
    } finally {
      setDeleteBusy(false);
    }
  }

  async function handleCancelRun(runId: string) {
    const confirmed = window.confirm("Cancel this grading run?");
    if (!confirmed) {
      return;
    }

    setCancelBusyId(runId);
    setError("");
    setSuccess("");
    try {
      await api.cancelGrading(runId);
      if (activeRunId === runId) {
        setActiveRunId(null);
      }
      await loadDashboard(selectedRun?.id === runId ? undefined : selectedRun?.id);
      setSuccess("Grading was canceled.");
    } catch (cancelError) {
      setError(getErrorMessage(cancelError));
    } finally {
      setCancelBusyId(null);
    }
  }

  if (sessionStatus === "checking") {
    return (
      <LoadingState
        message="Validating your session and loading saved grading runs."
        title="Preparing dashboard"
      />
    );
  }

  if (sessionStatus === "unauthenticated") {
    return (
      <section className="page-grid auth-grid public-page">
        <WelcomePanel />
        <div className="column">
          {error ? <ErrorAlert message={error} /> : null}
          {success ? <TransientMessage message={success} tone="success" /> : null}
          <AuthForm onAuthenticated={handleAuthenticated} />
        </div>
      </section>
    );
  }

  const isGradingInFlight =
    Boolean(activeRunId) ||
    (selectedRun != null && !isTerminalStatus(selectedRun.status)) ||
    runs.some((run) => batchRunIds.includes(run.id) && !isTerminalStatus(run.status));
  const activeBatchRuns = runs.filter((run) => batchRunIds.includes(run.id) && !isTerminalStatus(run.status));
  const hasActiveBatch = activeBatchRuns.length > 0;
  const batchQueue = activeBatchRuns
    .map((run) => ({
      id: run.id,
      label: run.student_filename,
      status: `${run.status} · ${run.status_message ?? run.status}`,
    }));
  const batchProcessingRun =
    runs.find((run) => batchRunIds.includes(run.id) && run.status === "processing")
    ?? (selectedRun && batchRunIds.includes(selectedRun.id) && selectedRun.status === "processing" ? selectedRun : null);
  const workspaceRun = hasActiveBatch ? batchProcessingRun : selectedRun;
  const completedCount = runs.filter((run) => run.status === "completed").length;
  const processingCount = runs.filter((run) => run.status === "processing" || run.status === "pending").length;
  const failedCount = runs.filter((run) => run.status === "failed").length;
  const canceledCount = runs.filter((run) => run.status === "canceled").length;
  const completedDurations = runs
    .filter((run) => run.status === "completed")
    .sort(
      (left, right) =>
        new Date(right.completed_at ?? right.updated_at).getTime()
        - new Date(left.completed_at ?? left.updated_at).getTime()
    )
    .slice(0, 5)
    .map((run) => run.duration_ms)
    .filter((duration): duration is number => typeof duration === "number" && duration > 0);
  const averageDurationSeconds =
    completedDurations.length > 0
      ? (completedDurations.reduce((sum, duration) => sum + duration, 0) / completedDurations.length / 1000).toFixed(1)
      : null;

  return (
    <AppShell
      sidebar={<Sidebar currentUserEmail={user?.email} />}
      topbar={
        <AppTopbar
          actions={
            <button
              className="ghost topbar-logout"
              onClick={() => {
                clearAccessToken();
                window.location.href = "/";
              }}
              type="button"
            >
              Log out
            </button>
          }
          eyebrow="Dashboard"
          meta={<StatusBadge tone="accent">{user?.email ?? "Authenticated"}</StatusBadge>}
          subtitle="Upload exam files, monitor grading progress, and review previous AI-assisted scoring runs."
          title="AI exam grading workspace"
        />
      }
    >
      <div className="content-stack">
        <section className="overview-grid" id="overview">
          <div className="overview-card overview-card-accent">
            <p className="overview-label">Saved runs</p>
            <div className="overview-value">{runs.length}</div>
            <span>Stored grading submissions</span>
          </div>
          <div className="overview-card">
            <p className="overview-label">Completed</p>
            <div className="overview-value">{completedCount}</div>
            <span>Finished grading reports</span>
          </div>
          <div className="overview-card">
            <p className="overview-label">Active queue</p>
            <div className="overview-value">{processingCount}</div>
            <span>Pending or processing runs</span>
          </div>
          <div className="overview-card">
            <p className="overview-label">Average time</p>
            <div className="overview-value">{averageDurationSeconds ? `${averageDurationSeconds}s` : "No completed runs"}</div>
            <span>
              {completedDurations.length > 0
                ? `Based on the last ${completedDurations.length} completed runs`
                : "No completed runs yet"}
            </span>
          </div>
        </section>

        <section className="workspace-grid">
          <div className="main-column">
            {error ? <ErrorAlert message={error} /> : null}
            {success ? <TransientMessage message={success} tone="success" /> : null}

            <div className="panel activity-panel">
              <div className="row between">
                <div>
                  <p className="eyebrow">Activity</p>
                  <h2>Current workspace</h2>
                </div>
                <StatusBadge tone={workspaceRun?.status === "failed" || workspaceRun?.status === "canceled" ? "error" : workspaceRun ? "accent" : "neutral"}>
                  {workspaceRun?.status ?? "No run selected"}
                </StatusBadge>
              </div>
              <div className="summary-grid activity-grid">
                <div>
                  <strong>Latest state</strong>
                  <p>
                    {workspaceRun?.status_message
                      ?? workspaceRun?.status
                      ?? (hasActiveBatch ? "Waiting for the next batch task to start processing." : "Choose or create a grading run.")}
                  </p>
                </div>
                <div>
                  <strong>Selected student</strong>
                  <p>{workspaceRun?.student_filename ?? studentPdf?.name ?? "No student file selected"}</p>
                </div>
                <div>
                  <strong>Selected exam</strong>
                  <p>{workspaceRun?.exam_filename ?? examPdf?.name ?? "No exam file selected"}</p>
                </div>
                <div>
                  <strong>Queue health</strong>
                  <p>{batchQueue.length > 0 ? `${batchQueue.length} runs still processing` : "No queued runs right now"}</p>
                </div>
              </div>
              {workspaceRun && (workspaceRun.status === "pending" || workspaceRun.status === "processing") ? (
                <div className="row">
                  <button
                    className="ghost mini"
                    disabled={cancelBusyId === workspaceRun.id}
                    onClick={() => void handleCancelRun(workspaceRun.id)}
                    type="button"
                  >
                    {cancelBusyId === workspaceRun.id ? "Canceling..." : "Cancel selected run"}
                  </button>
                </div>
              ) : null}
            </div>

            {workspaceRun?.status === "processing" && !batchRunIds.includes(workspaceRun.id) ? (
              <GradingProgressCard fileName={workspaceRun.student_filename} run={workspaceRun} title="Current grading run" />
            ) : null}

            {batchProcessingRun ? (
              <GradingProgressCard
                fileName={batchProcessingRun.student_filename}
                run={batchProcessingRun}
                title="Current batch task"
              />
            ) : null}

            <section id="new-grading">
              <FileUploadCard
                batchQueue={batchQueue}
                busy={busy}
                disabled={isGradingInFlight}
                examPdfName={examPdf?.name ?? ""}
                inputResetKey={uploadResetKey}
                mode={uploadMode}
                onExamChange={setExamPdf}
                onModeChange={handleModeChange}
                onRemoveExam={() => setExamPdf(null)}
                onRemoveStudent={() => setStudentPdf(null)}
                onRemoveStudentBatchItem={(index) =>
                  setStudentBatchPdfs((current) => current.filter((_, itemIndex) => itemIndex !== index))
                }
                onReuseRecentExam={reuseRecentExam}
                onReuseRecentStudent={reuseRecentStudent}
                onStudentBatchChange={setStudentBatchPdfs}
                onStudentChange={setStudentPdf}
                onSubmit={handleSubmit}
                recentExamFiles={recentExamFiles}
                recentStudentFiles={recentStudentFiles}
                studentPdfName={studentPdf?.name ?? ""}
                studentPdfNames={studentBatchPdfs.map((file) => file.name)}
              />
            </section>

            <GradingResult run={selectedRun} />
          </div>

          <div className="side-column" id="history">
            <div className="panel side-summary">
              <div className="row between">
                <div>
                  <p className="eyebrow">Overview</p>
                  <h2>Submission summary</h2>
                </div>
                <StatusBadge tone={isGradingInFlight ? "warning" : "success"}>
                  {isGradingInFlight ? "Busy" : "Available"}
                </StatusBadge>
              </div>
              <div className="summary-list">
                <div>
                  <strong>Ready to submit</strong>
                  <p>{isGradingInFlight ? "Wait for the active run to finish before starting another one." : "Single and batch grading are available."}</p>
                </div>
                <div>
                  <strong>Recent completions</strong>
                  <p>{completedCount > 0 ? `${completedCount} saved grading runs can be reopened or exported.` : "No completed runs saved yet."}</p>
                </div>
                <div>
                  <strong>Failure watch</strong>
                  <p>
                    {failedCount + canceledCount > 0
                      ? `${failedCount} failed and ${canceledCount} canceled runs are currently recorded.`
                      : "No failed or canceled runs are currently recorded."}
                  </p>
                </div>
              </div>
            </div>

            <GradingHistory
              cancelBusyId={cancelBusyId}
              deleteBusy={deleteBusy}
              exportBusy={exportBusy}
              onCancelRun={handleCancelRun}
              onDeleteSelected={handleDeleteSelected}
              onExportSelected={handleExportSelected}
              runs={runs}
              selectedRunId={selectedRun?.id ?? null}
            />
          </div>
        </section>
      </div>
    </AppShell>
  );
}
