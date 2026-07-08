"use client";

import { useEffect, useState } from "react";
import type { GradingRunStatus, GradingStage } from "@/types/api";

type ProgressRun = {
  status: GradingRunStatus;
  stage: GradingStage;
  progress_percent: number;
  status_message: string | null;
  started_at: string | null;
  error_message?: string | null;
};

function formatElapsed(startedAt: string | null) {
  if (!startedAt) {
    return "Not started";
  }
  const elapsedMs = Math.max(Date.now() - new Date(startedAt).getTime(), 0);
  const seconds = Math.floor(elapsedMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return minutes > 0 ? `${minutes}m ${remainingSeconds}s` : `${remainingSeconds}s`;
}

export function GradingProgressCard({
  fileName,
  run,
  title = "Live progress"
}: {
  fileName?: string;
  run: ProgressRun;
  title?: string;
}) {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!run.started_at || run.status === "completed" || run.status === "failed" || run.status === "canceled") {
      return;
    }
    const timer = window.setInterval(() => {
      setTick((value) => value + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [run.started_at, run.status]);

  const stageLabel = run.status_message || "Processing";

  return (
    <div className="panel progress-panel">
      <div className="row between">
        <div>
          <p className="eyebrow">Progress</p>
          <h2>{title}</h2>
        </div>
        <div className={`status-chip status-${run.status}`}>{run.status}</div>
      </div>
      <div className="stack">
        <p className="lede progress-copy">
          {stageLabel}. This can take up to around 1-2 minutes depending on PDF size.
        </p>
        <div className="progress-bar-shell" aria-hidden="true">
          <div className="progress-bar-fill" style={{ width: `${Math.min(run.progress_percent, 100)}%` }} />
        </div>
        <div className="row between muted">
          <span>{fileName ? `File: ${fileName}` : "Processing"}</span>
          {fileName ? <span>{run.progress_percent}%</span> : null}
          <span>Elapsed: {formatElapsed(run.started_at)}</span>
        </div>
        {run.error_message ? <p className="status status-error">{run.error_message}</p> : null}
      </div>
    </div>
  );
}
