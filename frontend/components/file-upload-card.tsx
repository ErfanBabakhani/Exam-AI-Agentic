"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { RecentFileEntry } from "@/lib/recent-files";

type UploadMode = "single" | "batch";

function RecentFilesModal({
  entries,
  onClose,
  onSelect,
  title,
}: {
  entries: RecentFileEntry[];
  onClose: () => void;
  onSelect: (entryId: string) => void;
  title: string;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sortedEntries = useMemo(
    () =>
      [...entries].sort(
        (left, right) => new Date(right.lastUsedAt).getTime() - new Date(left.lastUsedAt).getTime(),
      ),
    [entries],
  );
  const [showMoreHint, setShowMoreHint] = useState(false);
  const compactLayout = sortedEntries.length <= 3;

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
  }, [sortedEntries]);

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
        className={`modal-card${compactLayout ? " modal-card-compact" : ""}`}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="row between">
          <div>
            <p className="eyebrow">Recent files</p>
            <h2>{title}</h2>
          </div>
          <button className="ghost mini" onClick={onClose} type="button">
            Close
          </button>
        </div>
        <div className="stack scroll-stack modal-scroll" ref={scrollRef}>
          {sortedEntries.map((entry) => (
            <div className="recent-file-row" key={entry.id}>
              <div>
                <strong>{entry.name}</strong>
                <small>{new Date(entry.lastUsedAt).toLocaleString()}</small>
              </div>
              <button className="primary mini" onClick={() => onSelect(entry.id)} type="button">
                Use file
              </button>
            </div>
          ))}
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
        {sortedEntries.length > 0 ? (
          <small>Recent files are sorted by date and keep only the latest reusable item for each file name.</small>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}

function UploadDropzone({
  accept,
  description,
  disabled,
  fileNames,
  label,
  multiple = false,
  onFilesSelected,
  onRemoveFile,
}: {
  accept: string;
  description: string;
  disabled?: boolean;
  fileNames: string[];
  label: string;
  multiple?: boolean;
  onFilesSelected: (files: File[]) => void;
  onRemoveFile?: (index: number) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  function handleFiles(fileList: FileList | null) {
    const files = Array.from(fileList ?? []);
    if (files.length === 0) {
      return;
    }
    onFilesSelected(files);
  }

  return (
    <div
      className={`upload-field dropzone${isDragging ? " drag-active" : ""}${disabled ? " disabled-dropzone" : ""}`}
      onClick={() => {
        if (!disabled) {
          inputRef.current?.click();
        }
      }}
      onDragOver={(event) => {
        if (disabled) {
          return;
        }
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        if (disabled) {
          return;
        }
        event.preventDefault();
        setIsDragging(false);
        handleFiles(event.dataTransfer.files);
      }}
      role="button"
      tabIndex={0}
    >
      <span>{label}</span>
      <input
        accept={accept}
        disabled={disabled}
        hidden
        multiple={multiple}
        onChange={(event) => handleFiles(event.target.files)}
        ref={inputRef}
        type="file"
      />
      <div className="dropzone-copy">
        <strong>{multiple ? "Drag and drop files here" : "Drag and drop a file here"}</strong>
        <small>{description}</small>
        {fileNames.length > 0 ? (
          <div className="selected-file-list">
            {fileNames.map((name, index) => (
              <span className="file-chip removable-file-chip" key={`${name}-${index}`}>
                {onRemoveFile ? (
                  <button
                    aria-label={`Remove ${name}`}
                    className="file-chip-remove"
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      onRemoveFile(index);
                    }}
                    type="button"
                  >
                    ×
                  </button>
                ) : null}
                {name}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function FileUploadCard({
  batchQueue,
  busy,
  disabled,
  examPdfName,
  inputResetKey,
  mode,
  onExamChange,
  onModeChange,
  onReuseRecentExam,
  onReuseRecentStudent,
  onStudentBatchChange,
  onStudentChange,
  onRemoveExam,
  onRemoveStudent,
  onRemoveStudentBatchItem,
  onSubmit,
  recentExamFiles,
  recentStudentFiles,
  studentPdfName,
  studentPdfNames,
}: {
  batchQueue: { id: string; label: string; status: string }[];
  busy: boolean;
  disabled?: boolean;
  examPdfName: string;
  inputResetKey: number;
  mode: UploadMode;
  onExamChange: (file: File | null) => void;
  onModeChange: (mode: UploadMode) => void;
  onReuseRecentExam: (entryId: string) => void;
  onReuseRecentStudent: (entryId: string) => void;
  onStudentBatchChange: (files: File[]) => void;
  onStudentChange: (file: File | null) => void;
  onRemoveExam: () => void;
  onRemoveStudent: () => void;
  onRemoveStudentBatchItem: (index: number) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void> | void;
  recentExamFiles: RecentFileEntry[];
  recentStudentFiles: RecentFileEntry[];
  studentPdfName: string;
  studentPdfNames: string[];
}) {
  const [recentModalKind, setRecentModalKind] = useState<"exam" | "student" | null>(null);
  const modalEntries = useMemo(
    () => (recentModalKind === "exam" ? recentExamFiles : recentModalKind === "student" ? recentStudentFiles : []),
    [recentExamFiles, recentModalKind, recentStudentFiles],
  );

  return (
    <div className="panel">
      <div className="row between">
        <div>
          <p className="eyebrow">New Run</p>
          <h2>Upload exam and solution PDFs</h2>
        </div>
        <div className="segment">
          <button className={mode === "single" ? "active" : ""} onClick={() => onModeChange("single")} type="button">
            Single
          </button>
          <button className={mode === "batch" ? "active" : ""} onClick={() => onModeChange("batch")} type="button">
            Batch
          </button>
        </div>
      </div>
      <form className="stack" key={inputResetKey} onSubmit={onSubmit}>
        <UploadDropzone
          accept="application/pdf"
          description="Choose or drop the exam paper with official solutions."
          disabled={busy || disabled}
          fileNames={examPdfName ? [examPdfName] : []}
          label="Exam PDF"
          onFilesSelected={(files) => onExamChange(files[0] ?? null)}
          onRemoveFile={() => onRemoveExam()}
        />
        <div className="row recent-actions">
          <button
            className="ghost mini"
            disabled={recentExamFiles.length === 0}
            onClick={() => setRecentModalKind("exam")}
            type="button"
          >
            Recent exam files
          </button>
        </div>
        <UploadDropzone
          accept="application/pdf"
          description={
            mode === "batch"
              ? "Choose or drop several student submissions to queue them against the same exam."
              : "Choose or drop one handwritten student submission."
          }
          disabled={busy || disabled}
          fileNames={mode === "batch" ? studentPdfNames : studentPdfName ? [studentPdfName] : []}
          label={mode === "batch" ? "Student solution PDFs" : "Student answer PDF"}
          multiple={mode === "batch"}
          onFilesSelected={(files) => {
            if (mode === "batch") {
              onStudentBatchChange(files);
              return;
            }
            onStudentChange(files[0] ?? null);
          }}
          onRemoveFile={(index) => {
            if (mode === "batch") {
              onRemoveStudentBatchItem(index);
              return;
            }
            onRemoveStudent();
          }}
        />
        <div className="row recent-actions">
          <button
            className="ghost mini"
            disabled={recentStudentFiles.length === 0}
            onClick={() => setRecentModalKind("student")}
            type="button"
          >
            Recent student files
          </button>
        </div>
        <button className="primary" disabled={busy || disabled} type="submit">
          {busy ? "Starting grading..." : disabled ? "Wait for current run" : mode === "batch" ? "Queue batch grading" : "Submit grading"}
        </button>
        <small>
          {mode === "batch"
            ? "Batch mode creates one grading run per student file and processes them as a queue."
            : "Once the run starts, the dashboard will keep updating its status and progress automatically."}
        </small>
      </form>
      {batchQueue.length > 0 ? (
        <div className="batch-queue">
          <div className="row between">
            <strong>Current batch queue</strong>
            <small>{batchQueue.length} runs</small>
          </div>
          <div className="stack scroll-stack compact-scroll-stack">
            {batchQueue.map((item) => (
              <div className="queue-item" key={item.id}>
                <span>{item.label}</span>
                <small>{item.status}</small>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {recentModalKind && modalEntries.length > 0 ? (
        <RecentFilesModal
          entries={modalEntries}
          onClose={() => setRecentModalKind(null)}
          onSelect={(entryId) => {
            if (recentModalKind === "exam") {
              onReuseRecentExam(entryId);
            } else {
              onReuseRecentStudent(entryId);
            }
            setRecentModalKind(null);
          }}
          title={recentModalKind === "exam" ? "Reuse a recent exam file" : "Reuse a recent student file"}
        />
      ) : null}
    </div>
  );
}
