"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, getErrorMessage, isBackgroundNetworkError, type GradingRunDetail, type GradingRunSummary, type TokenResponse } from "@/lib/api";
import { clearAccessToken, hasAccessToken, persistAccessToken } from "@/lib/auth";
import { AppShell } from "@/components/app-shell";
import { AppTopbar } from "@/components/app-topbar";
import { AuthForm } from "@/components/auth-form";
import { ErrorAlert } from "@/components/error-alert";
import { GradingProgressCard } from "@/components/grading-progress-card";
import { LoadingState } from "@/components/loading-state";
import { Sidebar } from "@/components/sidebar";
import { StatusBadge } from "@/components/status-badge";
import { TransientMessage } from "@/components/transient-message";
import { WelcomePanel } from "@/components/welcome-panel";
import { hasDistinctEvidenceSummaries } from "@/lib/grading-feedback";

type SessionState = "checking" | "authenticated" | "unauthenticated";

function isTerminal(status: string) {
  return status === "completed" || status === "failed" || status === "canceled";
}

function renderItems(title: string, items: string[]) {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="feedback-group">
      <strong>{title}</strong>
      <ul className="feedback-list">
        {items.map((item) => (
          <li key={`${title}-${item}`}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function TaskSelectionModal({
  currentTaskId,
  onClose,
  runs,
}: {
  currentTaskId: string;
  onClose: () => void;
  runs: GradingRunSummary[];
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [showMoreHint, setShowMoreHint] = useState(false);

  useEffect(() => {
    function updateMoreHint() {
      const container = scrollRef.current;
      if (!container) {
        setShowMoreHint(false);
        return;
      }
      setShowMoreHint(container.scrollHeight - container.scrollTop - container.clientHeight > 8);
    }

    updateMoreHint();
    const container = scrollRef.current;
    if (!container) {
      return;
    }
    container.addEventListener("scroll", updateMoreHint);
    window.addEventListener("resize", updateMoreHint);
    return () => {
      container.removeEventListener("scroll", updateMoreHint);
      window.removeEventListener("resize", updateMoreHint);
    };
  }, [runs]);

  useEffect(() => {
    const previousBodyOverflow = document.body.style.overflow;
    const previousHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousBodyOverflow;
      document.documentElement.style.overflow = previousHtmlOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  if (typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-card detail-task-modal-card"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="row between">
          <div>
            <p className="eyebrow">Another Task</p>
            <h2>Open a different grading task</h2>
          </div>
          <button className="ghost mini" onClick={onClose} type="button">
            Close
          </button>
        </div>
        <div className="detail-task-modal-frame">
          <div className="stack scroll-stack detail-task-modal-scroll" ref={scrollRef}>
            {runs.map((item) => (
              <div className={`run-card${currentTaskId === item.id ? " selected" : ""}`} key={item.id}>
                <div className="row between run-card-toolbar">
                  <strong>{item.status}</strong>
                  {currentTaskId === item.id ? (
                    <span className="status-badge status-badge-accent">Current</span>
                  ) : (
                    <Link className="ghost-link mini" href={`/gradings/${item.id}`}>
                      Open
                    </Link>
                  )}
                </div>
                <Link className="run-card-link" href={`/gradings/${item.id}`}>
                  <div className="row between">
                    <small>{item.status_message ?? item.status}</small>
                    <small>{item.duration_ms ? `${(item.duration_ms / 1000).toFixed(1)}s` : `${item.progress_percent}%`}</small>
                  </div>
                  <p>{item.student_filename}</p>
                  <small>Exam: {item.exam_filename}</small>
                  <small>{new Date(item.created_at).toLocaleString()}</small>
                </Link>
              </div>
            ))}
          </div>
        </div>
        {showMoreHint ? (
          <button
            className="recent-more-hint"
            onClick={() => {
              scrollRef.current?.scrollBy({ top: 220, behavior: "smooth" });
            }}
            type="button"
          >
            More ↓
          </button>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}

export function GradingDetailPage({ gradingId }: { gradingId: string }) {
  const [sessionState, setSessionState] = useState<SessionState>("checking");
  const [run, setRun] = useState<GradingRunDetail | null>(null);
  const [availableRuns, setAvailableRuns] = useState<GradingRunSummary[]>([]);
  const [currentUserEmail, setCurrentUserEmail] = useState("");
  const [detailsQuestionId, setDetailsQuestionId] = useState("");
  const [overrideQuestionId, setOverrideQuestionId] = useState("");
  const [newScore, setNewScore] = useState("0");
  const [reason, setReason] = useState("Teacher adjustment");
  const [busy, setBusy] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [isTaskModalOpen, setIsTaskModalOpen] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const questionIds = useMemo(
    () => run?.result?.questions.map((question) => question.question_id) ?? [],
    [run],
  );
  const selectedQuestion = useMemo(
    () =>
      run?.result?.questions.find((question) => question.question_id === detailsQuestionId)
      ?? run?.result?.questions[0]
      ?? null,
    [detailsQuestionId, run],
  );
  const selectedTaskId = run?.id ?? gradingId;

  async function loadRun() {
    const [detail, runs] = await Promise.all([api.getGrading(gradingId), api.listGradings()]);
    setRun(detail);
    setAvailableRuns(runs);
  }

  useEffect(() => {
    async function validateAndLoad() {
      if (!hasAccessToken()) {
        setSessionState("unauthenticated");
        return;
      }

      try {
        const currentUser = await api.me();
        setCurrentUserEmail(currentUser.email);
        await loadRun();
        setSessionState("authenticated");
      } catch (loadError) {
        setError(getErrorMessage(loadError));
        setSessionState(hasAccessToken() ? "authenticated" : "unauthenticated");
      }
    }

    void validateAndLoad();
  }, [gradingId]);

  useEffect(() => {
    if (!questionIds.length) {
      setDetailsQuestionId("");
      setOverrideQuestionId("");
      return;
    }
    if (!questionIds.includes(detailsQuestionId)) {
      setDetailsQuestionId(questionIds[0]);
    }
    if (!questionIds.includes(overrideQuestionId)) {
      setOverrideQuestionId(questionIds[0]);
    }
  }, [detailsQuestionId, overrideQuestionId, questionIds]);

  useEffect(() => {
    if (!run || isTerminal(run.status)) {
      return;
    }

    const poll = window.setInterval(async () => {
      try {
        const statusPayload = await api.getGradingStatus(gradingId);
        setRun((current) => (current ? { ...current, ...statusPayload } : current));
        if (isTerminal(statusPayload.status)) {
          window.clearInterval(poll);
          await loadRun();
        }
      } catch (pollError) {
        if (!hasAccessToken()) {
          setSessionState("unauthenticated");
          setRun(null);
          window.clearInterval(poll);
          return;
        }
        if (!isBackgroundNetworkError(pollError)) {
          setError(getErrorMessage(pollError));
          window.clearInterval(poll);
        }
      }
    }, 2000);

    return () => window.clearInterval(poll);
  }, [gradingId, run?.status]);

  async function handleAuthenticated(token: TokenResponse, successMessage: string) {
    persistAccessToken(token.access_token);
    setError("");
    setSuccess(successMessage);
    window.location.href = `/gradings/${gradingId}`;
  }

  async function onOverride(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSuccess("");

    try {
      await api.overrideGrade(gradingId, {
        question_id: overrideQuestionId,
        new_score: Number(newScore),
        reason,
      });
      await loadRun();
      setSuccess("Override saved.");
    } catch (overrideError) {
      setError(getErrorMessage(overrideError));
    } finally {
      setBusy(false);
    }
  }

  async function onCancel() {
    const confirmed = window.confirm("Cancel this grading run?");
    if (!confirmed) {
      return;
    }

    setCancelBusy(true);
    setError("");
    setSuccess("");
    try {
      await api.cancelGrading(gradingId);
      await loadRun();
      setSuccess("Grading was canceled.");
    } catch (cancelError) {
      setError(getErrorMessage(cancelError));
    } finally {
      setCancelBusy(false);
    }
  }

  if (sessionState === "checking") {
    return (
      <LoadingState
        message="Checking your session and loading the requested grading run."
        title="Loading grading detail"
      />
    );
  }

  if (sessionState === "unauthenticated") {
    return (
      <section className="page-grid auth-grid public-page">
        <WelcomePanel />
        <div className="column">
          {error ? <ErrorAlert message={error} /> : null}
          {success ? <TransientMessage message={success} tone="success" /> : null}
          <AuthForm initialMode="login" onAuthenticated={handleAuthenticated} />
        </div>
      </section>
    );
  }

  return (
    <AppShell
      sidebar={<Sidebar currentUserEmail={currentUserEmail} />}
      topbar={
        <AppTopbar
          actions={
            <>
              <StatusBadge tone={run?.status === "failed" || run?.status === "canceled" ? "error" : run?.status === "completed" ? "success" : "warning"}>
                {run?.status ?? "Unknown"}
              </StatusBadge>
              {run && (run.status === "pending" || run.status === "processing") ? (
                <button className="ghost mini" disabled={cancelBusy} onClick={() => void onCancel()} type="button">
                  {cancelBusy ? "Canceling..." : "Cancel"}
                </button>
              ) : null}
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
            </>
          }
          eyebrow="Saved run"
          meta={currentUserEmail ? <StatusBadge tone="accent">{currentUserEmail}</StatusBadge> : null}
          subtitle="Review the stored grading output, inspect the AI rationale, and apply teacher overrides when needed."
          title={run?.student_filename ? `Grading details for ${run.student_filename}` : "Loading grading details"}
        />
      }
    >
      <div className="content-stack">
        {isTaskModalOpen ? (
          <TaskSelectionModal
            currentTaskId={selectedTaskId}
            onClose={() => setIsTaskModalOpen(false)}
            runs={availableRuns}
          />
        ) : null}
        <section className="overview-grid">
          <div className="overview-card overview-card-accent">
            <p className="overview-label">Score</p>
            <div className="overview-value">
              {run?.total_score ?? 0} / {run?.max_score ?? 0}
            </div>
            <span>Stored grading total</span>
          </div>
          <div className="overview-card">
            <p className="overview-label">Duration</p>
            <div className="overview-value">{run?.duration_ms ? `${(run.duration_ms / 1000).toFixed(1)}s` : "N/A"}</div>
            <span>Recorded completion time</span>
          </div>
          <div className="overview-card">
            <p className="overview-label">Student file</p>
            <div className="overview-value-compact">{run?.student_filename ?? "Unknown"}</div>
            <span>Submission attached to this run</span>
          </div>
          <div className="overview-card">
            <p className="overview-label">Exam file</p>
            <div className="overview-value-compact">{run?.exam_filename ?? "Unknown"}</div>
            <span>Reference exam or mark scheme</span>
          </div>
        </section>

        <section className="workspace-grid detail-workspace-grid">
          <div className="main-column">
            {error ? <ErrorAlert message={error} /> : null}
            {success ? <TransientMessage message={success} tone="success" /> : null}
            {run?.status === "processing" ? <GradingProgressCard fileName={run.student_filename} run={run} title="Current run" /> : null}

            <div className="panel">
              <div className="row between">
                <div>
                  <p className="eyebrow">Run Summary</p>
                  <h2>Stored grading details</h2>
                </div>
                <StatusBadge tone="accent">{run?.model_deployment ?? "deployment unknown"}</StatusBadge>
              </div>
              <div className="meta-grid">
                <div>
                  <strong>Status</strong>
                  <p>{run?.status ?? "Unknown"}</p>
                </div>
                <div>
                  <strong>Duration</strong>
                  <p>{run?.duration_ms ? `${(run.duration_ms / 1000).toFixed(1)}s` : "Not recorded"}</p>
                </div>
                <div>
                  <strong>Updated</strong>
                  <p>{run ? new Date(run.updated_at).toLocaleString() : "Unknown"}</p>
                </div>
                <div>
                  <strong>Started</strong>
                  <p>{run?.started_at ? new Date(run.started_at).toLocaleString() : "Not recorded"}</p>
                </div>
                <div>
                  <strong>Completed</strong>
                  <p>{run?.completed_at ? new Date(run.completed_at).toLocaleString() : "Not recorded"}</p>
                </div>
                {run?.error_message ? (
                  <div>
                    <strong>Failure reason</strong>
                    <p>{run.error_message}</p>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="panel">
              <p className="eyebrow">Questions</p>
              <h2>Stored question results</h2>
              {run?.error_message ? <ErrorAlert message={run.error_message} /> : null}
              {selectedQuestion ? (
                <div className="stack">
                  <label>
                    <span>Question</span>
                    <select onChange={(event) => setDetailsQuestionId(event.target.value)} value={selectedQuestion.question_id}>
                      {questionIds.map((id) => (
                        <option key={id} value={id}>
                          Question {id}
                        </option>
                      ))}
                    </select>
                  </label>
                  {questionIds.length > 1 ? (
                    <div className="quick-picks">
                      {questionIds.slice(0, 8).map((id) => (
                        <button
                          className={`ghost mini${detailsQuestionId === id ? " selected-chip" : ""}`}
                          key={id}
                          onClick={() => setDetailsQuestionId(id)}
                          type="button"
                        >
                          {id}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {(() => {
                    const correctElements = selectedQuestion.correct_elements ?? [];
                    const missingElements = selectedQuestion.missing_or_incorrect_elements ?? [];
                    const improvementSuggestions = selectedQuestion.improvement_suggestions ?? [];
                    const evidenceSummaries = selectedQuestion.evidence_summaries ?? [];
                    const visibleEvidence = selectedQuestion.visible_evidence ?? [];
                    const showEvidenceSummaries = hasDistinctEvidenceSummaries(visibleEvidence, evidenceSummaries);
                    return (
                      <article className="question-card" key={selectedQuestion.question_id}>
                        <div className="row between">
                          <strong>Question {selectedQuestion.question_id}</strong>
                          <span>
                            {selectedQuestion.awarded_marks} / {selectedQuestion.max_marks}
                          </span>
                        </div>
                        <div className="question-card-scroll">
                          <p>{selectedQuestion.score_rationale || selectedQuestion.feedback}</p>
                          {renderItems("What was correct", correctElements)}
                          {renderItems("What was missing or incorrect", missingElements)}
                          {renderItems("How to improve", improvementSuggestions)}
                          {visibleEvidence.length > 0 ? (
                            <div className="feedback-group">
                              <strong>Visible evidence</strong>
                              <ul className="feedback-list">
                                {visibleEvidence.map((item, index) => (
                                  <li key={`${selectedQuestion.question_id}-visible-${index}`}>
                                    {item.page ? `Page ${item.page}: ` : ""}
                                    {item.evidence}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ) : null}
                          {showEvidenceSummaries ? (
                            <div className="feedback-group">
                              <strong>Evidence used</strong>
                              <ul className="feedback-list">
                                {evidenceSummaries.map((item, index) => (
                                  <li key={`${selectedQuestion.question_id}-evidence-${index}`}>
                                    {item.page ? `Page ${item.page}: ` : ""}
                                    {item.summary}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ) : null}
                        </div>
                        <small>
                          {selectedQuestion.criterion_scores.length} rubric criteria scored
                          {run?.duration_ms ? ` · Run duration ${(run.duration_ms / 1000).toFixed(1)}s` : ""}
                        </small>
                      </article>
                    );
                  })()}
                </div>
              ) : (
                <p className="muted">No result payload is available for this run yet.</p>
              )}
            </div>
          </div>

          <div className="side-column">
            <div className="panel detail-task-switch-panel">
              <p className="eyebrow">Another Task</p>
              <h2>Browse saved grading tasks</h2>
              <div className="stack">
                <small>
                  Open the previous-page style task list in a popup without leaving this screen.
                </small>
                <button className="primary" onClick={() => setIsTaskModalOpen(true)} type="button">
                  Open task list
                </button>
              </div>
            </div>

            <div className="panel detail-override-panel">
              <p className="eyebrow">Teacher Override</p>
              <h2>Adjust a question score</h2>
              <form className="stack" onSubmit={onOverride}>
                <label>
                  <span>Question ID</span>
                  <select onChange={(event) => setOverrideQuestionId(event.target.value)} required value={overrideQuestionId}>
                    <option value="" disabled>
                      Choose a question
                    </option>
                    {questionIds.map((id) => (
                      <option key={id} value={id}>
                        Question {id}
                      </option>
                    ))}
                  </select>
                </label>
                {questionIds.length > 0 ? (
                  <div className="quick-picks">
                    {questionIds.slice(0, 6).map((id) => (
                      <button
                        className={`ghost mini${overrideQuestionId === id ? " selected-chip" : ""}`}
                        key={id}
                        onClick={() => setOverrideQuestionId(id)}
                        type="button"
                      >
                        {id}
                      </button>
                    ))}
                  </div>
                ) : null}
                <label>
                  <span>New score</span>
                  <input
                    min="0"
                    onChange={(event) => setNewScore(event.target.value)}
                    step="0.5"
                    type="number"
                    value={newScore}
                  />
                </label>
                <label>
                  <span>Reason</span>
                  <textarea onChange={(event) => setReason(event.target.value)} rows={4} value={reason} />
                </label>
                <button className="primary" disabled={busy} type="submit">
                  {busy ? "Saving override..." : "Save override"}
                </button>
              </form>
            </div>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
