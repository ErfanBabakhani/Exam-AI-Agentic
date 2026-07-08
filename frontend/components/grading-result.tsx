"use client";

import { useEffect, useMemo, useState } from "react";
import type { GradingRunDetail } from "@/types/api";
import { GradingProgressCard } from "@/components/grading-progress-card";
import { hasDistinctEvidenceSummaries } from "@/lib/grading-feedback";

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

export function GradingResult({ run }: { run: GradingRunDetail | null }) {
  const questions = useMemo(() => run?.result?.questions ?? [], [run]);
  const [selectedQuestionId, setSelectedQuestionId] = useState("");

  useEffect(() => {
    if (!questions.length) {
      setSelectedQuestionId("");
      return;
    }
    if (!questions.some((question) => question.question_id === selectedQuestionId)) {
      setSelectedQuestionId(questions[0].question_id);
    }
  }, [questions, selectedQuestionId]);

  const selectedQuestion = questions.find((question) => question.question_id === selectedQuestionId) ?? questions[0] ?? null;

  return (
    <div className="panel result-panel">
      <div className="row between">
        <div>
          <p className="eyebrow">Result</p>
          <h2>Latest grading result</h2>
        </div>
        {run ? (
          <div className="score-pill">
            {run.total_score ?? 0} / {run.max_score ?? 0}
          </div>
        ) : null}
      </div>

      {!run ? <p className="muted">Submit a grading run to inspect structured results here.</p> : null}

      {run ? (
        <div className="stack">
          {run.status === "processing" ? (
            <GradingProgressCard fileName={run.student_filename} run={run} title="Run progress" />
          ) : null}
          <div className="summary-grid compact-summary-grid">
            <div>
              <strong>Status</strong>
              <p>{run.status}</p>
            </div>
            <div>
              <strong>Duration</strong>
              <p>{run.duration_ms ? `${(run.duration_ms / 1000).toFixed(1)}s` : "Not recorded"}</p>
            </div>
            <div>
              <strong>Model</strong>
              <p>{run.model_deployment ?? "Not recorded"}</p>
            </div>
            <div>
              <strong>Updated</strong>
              <p>{new Date(run.updated_at).toLocaleString()}</p>
            </div>
          </div>

          {run.error_message ? <p className="status status-error">{run.error_message}</p> : null}

          {!run.result ? (
            <p className="muted">This run does not have a grading payload yet. The dashboard will keep polling while it is processing.</p>
          ) : null}

          {selectedQuestion ? (
            <div className="stack">
              <label>
                <span>Question</span>
                <select onChange={(event) => setSelectedQuestionId(event.target.value)} value={selectedQuestion.question_id}>
                  {questions.map((question) => (
                    <option key={question.question_id} value={question.question_id}>
                      Question {question.question_id}
                    </option>
                  ))}
                </select>
              </label>
              {questions.length > 1 ? (
                <div className="quick-picks">
                  {questions.slice(0, 8).map((question) => (
                    <button
                      className={`ghost mini${selectedQuestion.question_id === question.question_id ? " selected-chip" : ""}`}
                      key={question.question_id}
                      onClick={() => setSelectedQuestionId(question.question_id)}
                      type="button"
                    >
                      {question.question_id}
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
                    <small>{selectedQuestion.criterion_scores.length} rubric criteria scored</small>
                  </article>
                );
              })()}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
