"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { GradingRunSummary } from "@/types/api";

function formatDuration(durationMs: number | null) {
  if (!durationMs || durationMs <= 0) {
    return "in progress";
  }
  return `${(durationMs / 1000).toFixed(1)}s`;
}

export function GradingHistory({
  cancelBusyId = null,
  deleteBusy = false,
  exportBusy = false,
  onCancelRun,
  onDeleteSelected,
  onExportSelected,
  runs,
  selectedRunId
}: {
  cancelBusyId?: string | null;
  deleteBusy?: boolean;
  exportBusy?: boolean;
  onCancelRun: (runId: string) => void | Promise<void>;
  onDeleteSelected: (runIds: string[]) => void | Promise<void>;
  onExportSelected: (runIds: string[], format: "csv" | "txt" | "pdf") => void | Promise<void>;
  runs: GradingRunSummary[];
  selectedRunId?: string | null;
}) {
  const [statusFilter, setStatusFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectionMode, setSelectionMode] = useState(false);
  const [exportFormat, setExportFormat] = useState<"" | "csv" | "txt" | "pdf">("");

  const filteredRuns = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return runs.filter((run) => {
      if (statusFilter !== "all" && run.status !== statusFilter) {
        return false;
      }
      if (!normalizedQuery) {
        return true;
      }
      return [run.exam_filename, run.student_filename].join(" ").toLowerCase().includes(normalizedQuery);
    });
  }, [query, runs, statusFilter]);

  useEffect(() => {
    const runIds = new Set(runs.map((run) => run.id));
    setSelectedIds((current) => current.filter((id) => runIds.has(id)));
  }, [runs]);

  const filteredRunIds = filteredRuns.map((run) => run.id);
  const allFilteredSelected =
    filteredRunIds.length > 0 && filteredRunIds.every((runId) => selectedIds.includes(runId));
  const selectedRuns = runs.filter((run) => selectedIds.includes(run.id));
  const hasNonTerminalSelection = selectedRuns.some((run) => run.status !== "completed" && run.status !== "failed" && run.status !== "canceled");

  function toggleRun(runId: string) {
    setSelectedIds((current) => (current.includes(runId) ? current.filter((id) => id !== runId) : [...current, runId]));
  }

  function toggleAllFiltered() {
    setSelectedIds((current) => {
      if (allFilteredSelected) {
        return current.filter((id) => !filteredRunIds.includes(id));
      }
      return Array.from(new Set([...current, ...filteredRunIds]));
    });
  }

  function toggleSelectionMode() {
    setSelectionMode((current) => {
      if (current) {
        setSelectedIds([]);
        setExportFormat("");
      }
      return !current;
    });
  }

  return (
    <div className="panel history-panel">
      <div className="row between">
        <div>
          <p className="eyebrow">History</p>
          <h2>Saved grading runs</h2>
        </div>
        <button className={`ghost mini${selectionMode ? " active-export-toggle" : ""}`} onClick={toggleSelectionMode} type="button">
          {selectionMode ? "Done selecting" : "Select"}
        </button>
      </div>
      <div className="history-filters">
        <input
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter by file name"
          value={query}
        />
        <select onChange={(event) => setStatusFilter(event.target.value)} value={statusFilter}>
          <option value="all">All statuses</option>
          <option value="pending">Pending</option>
          <option value="processing">Processing</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="canceled">Canceled</option>
        </select>
      </div>
      {selectionMode ? (
        <div className="history-export-bar">
          <label className="history-selection-toggle">
            <input checked={allFilteredSelected} onChange={toggleAllFiltered} type="checkbox" />
            <span>{selectedIds.length} selected</span>
          </label>
          <div className="history-export-actions">
            <select
              aria-label="Select export format"
              className="history-export-select"
              onChange={(event) => setExportFormat(event.target.value as "" | "csv" | "txt" | "pdf")}
              value={exportFormat}
            >
              <option value="">Export as</option>
              <option value="csv">CSV</option>
              <option value="txt">Plain text</option>
              <option value="pdf">PDF</option>
            </select>
            <button
              className="primary mini"
              disabled={exportBusy || selectedIds.length === 0 || !exportFormat}
              onClick={() => {
                if (!exportFormat) {
                  return;
                }
                void onExportSelected(selectedIds, exportFormat);
              }}
              type="button"
            >
              Export
            </button>
            <button
              className="ghost mini"
              disabled={deleteBusy || selectedIds.length === 0 || hasNonTerminalSelection}
              onClick={() => {
                void onDeleteSelected(selectedIds);
              }}
              type="button"
            >
              {deleteBusy ? "Removing..." : "Remove"}
            </button>
          </div>
        </div>
      ) : null}
      {selectionMode && hasNonTerminalSelection ? (
        <p className="muted">Only completed, failed, or canceled runs can be removed. Export still works for the current selection.</p>
      ) : null}
      <div className="history-list-frame">
        <div className="stack scroll-stack history-scroll-stack">
          {filteredRuns.length === 0 ? <p className="muted">No grading runs match the current filter.</p> : null}
          {filteredRuns.map((run) => (
            <div className={`run-card${selectedRunId === run.id ? " selected" : ""}`} key={run.id}>
              <div className="row between run-card-toolbar">
                {selectionMode ? (
                  <label className="history-selection-toggle">
                    <input
                      checked={selectedIds.includes(run.id)}
                      onChange={() => toggleRun(run.id)}
                      type="checkbox"
                    />
                    <strong>{run.status}</strong>
                  </label>
                ) : (
                  <strong>{run.status}</strong>
                )}
                <div className="row">
                  <span>
                    {run.total_score ?? 0} / {run.max_score ?? 0}
                  </span>
                  {run.status === "pending" || run.status === "processing" ? (
                    <button
                      className="ghost mini"
                      disabled={cancelBusyId === run.id}
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        void onCancelRun(run.id);
                      }}
                      type="button"
                    >
                      {cancelBusyId === run.id ? "Canceling..." : "Cancel"}
                    </button>
                  ) : null}
                  <Link className="ghost-link mini" href={`/gradings/${run.id}`}>
                    Open
                  </Link>
                </div>
              </div>
              <Link className="run-card-link" href={`/gradings/${run.id}`}>
                <div className="row between">
                  <small>{run.status_message ?? run.status}</small>
                  <small>{run.duration_ms ? formatDuration(run.duration_ms) : `${run.progress_percent}%`}</small>
                </div>
                <p>{run.student_filename}</p>
                <small>Exam: {run.exam_filename}</small>
                <small>{run.status_message ?? run.model_deployment ?? "deployment not recorded"}</small>
                <small>{new Date(run.created_at).toLocaleString()}</small>
              </Link>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
