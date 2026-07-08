import type { GradingRunDetail } from "@/types/api";

function formatDuration(durationMs: number | null) {
  if (!durationMs || durationMs <= 0) {
    return "in progress";
  }
  return `${(durationMs / 1000).toFixed(1)}s`;
}

function formatDate(value: string | null) {
  if (!value) {
    return "not recorded";
  }
  return new Date(value).toLocaleString();
}

function sanitizeFileNamePart(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function buildExportFileName(format: "csv" | "txt" | "pdf", runCount: number) {
  const date = new Date().toISOString().slice(0, 10);
  return `grading-runs-${runCount}-${sanitizeFileNamePart(date)}.${format}`;
}

function triggerDownloadBlob(blob: Blob, fileName: string) {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

function triggerDownload(content: BlobPart, fileName: string, type: string) {
  triggerDownloadBlob(new Blob([content], { type }), fileName);
}

function csvEscape(value: string | number | null | undefined) {
  const normalized = value == null ? "" : String(value);
  return `"${normalized.replaceAll('"', '""')}"`;
}

function serializeQuestions(run: GradingRunDetail) {
  if (!run.result?.questions?.length) {
    return "No question results recorded.";
  }
  return run.result.questions
    .map((question, index) => {
      const rationale = question.score_rationale || question.feedback || "No rationale recorded.";
      return `${index + 1}. ${question.question_id}: ${question.awarded_marks}/${question.max_marks}. ${rationale}`;
    })
    .join(" | ");
}

function buildTextExport(runs: GradingRunDetail[]) {
  return runs
    .map((run) => {
      const header = [
        `Status: ${run.status}`,
        `Student file: ${run.student_filename}`,
        `Exam file: ${run.exam_filename}`,
        `Score: ${run.total_score ?? 0} / ${run.max_score ?? 0}`,
        `Duration: ${formatDuration(run.duration_ms)}`,
        `Created: ${formatDate(run.created_at)}`,
        `Completed: ${formatDate(run.completed_at)}`,
        `Message: ${run.status_message ?? run.error_message ?? "No status message recorded."}`,
      ].join("\n");

      const questions = run.result?.questions?.length
        ? run.result.questions
            .map((question) => {
              const lines = [
                `- ${question.question_id}: ${question.awarded_marks}/${question.max_marks}`,
                `  Rationale: ${question.score_rationale || question.feedback || "No rationale recorded."}`,
              ];
              if (question.correct_elements?.length) {
                lines.push(`  Correct: ${question.correct_elements.join("; ")}`);
              }
              if (question.missing_or_incorrect_elements?.length) {
                lines.push(`  Missing/incorrect: ${question.missing_or_incorrect_elements.join("; ")}`);
              }
              if (question.improvement_suggestions?.length) {
                lines.push(`  Improve: ${question.improvement_suggestions.join("; ")}`);
              }
              if (question.visible_evidence?.length) {
                lines.push(
                  `  Visible evidence: ${question.visible_evidence
                    .map((item) => `${item.page ? `Page ${item.page}: ` : ""}${item.evidence}`)
                    .join(" | ")}`,
                );
              }
              if (question.evidence_summaries?.length) {
                lines.push(
                  `  Evidence used: ${question.evidence_summaries
                    .map((item) => `${item.page ? `Page ${item.page}: ` : ""}${item.summary}`)
                    .join(" | ")}`,
                );
              }
              return lines.join("\n");
            })
            .join("\n")
        : "No per-question results recorded.";

      return `${header}\n\nQuestions\n${questions}`;
    })
    .join("\n\n========================================\n\n");
}

function buildCsvExport(runs: GradingRunDetail[]) {
  const header = [
    "status",
    "student_filename",
    "exam_filename",
    "total_score",
    "max_score",
    "duration",
    "created_at",
    "completed_at",
    "status_message",
    "questions_summary",
  ].join(",");

  const rows = runs.map((run) =>
    [
      csvEscape(run.status),
      csvEscape(run.student_filename),
      csvEscape(run.exam_filename),
      csvEscape(run.total_score ?? 0),
      csvEscape(run.max_score ?? 0),
      csvEscape(formatDuration(run.duration_ms)),
      csvEscape(formatDate(run.created_at)),
      csvEscape(formatDate(run.completed_at)),
      csvEscape(run.status_message ?? run.error_message ?? ""),
      csvEscape(serializeQuestions(run)),
    ].join(",")
  );

  return [header, ...rows].join("\n");
}

function escapePdfText(value: string) {
  return value.replaceAll("\\", "\\\\").replaceAll("(", "\\(").replaceAll(")", "\\)");
}

function buildPdfDocument(text: string) {
  const lines = text.split("\n");
  const objects: string[] = [];
  const pageObjectIds: number[] = [];
  const pageCount = Math.max(1, Math.ceil(lines.length / 44));
  const fontObjectId = 3 + pageCount * 2;
  let currentObjectId = 3;

  for (let start = 0; start < lines.length; start += 44) {
    const chunk = lines.slice(start, start + 44);
    const contentObjectId = currentObjectId++;
    const pageObjectId = currentObjectId++;
    pageObjectIds.push(pageObjectId);

    const contentLines = [
      "BT",
      "/F1 10 Tf",
      "50 792 Td",
      "14 TL",
      ...chunk.map((line, index) => `${index === 0 ? "" : "T* " }(${escapePdfText(line || " ")}) Tj`.trim()),
      "ET",
    ].join("\n");

    objects[contentObjectId - 1] = `${contentObjectId} 0 obj
<< /Length ${contentLines.length} >>
stream
${contentLines}
endstream
endobj`;
    objects[pageObjectId - 1] = `${pageObjectId} 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 ${fontObjectId} 0 R >> >> /Contents ${contentObjectId} 0 R >>
endobj`;
  }

  objects[1] = `2 0 obj
<< /Type /Pages /Count ${pageObjectIds.length} /Kids [${pageObjectIds.map((id) => `${id} 0 R`).join(" ")}] >>
endobj`;
  objects[fontObjectId - 1] = `${fontObjectId} 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj`;
  objects[0] = `1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj`;

  const orderedObjects = objects.filter(Boolean);
  let pdf = "%PDF-1.4\n";
  const offsets = [0];

  for (const object of orderedObjects) {
    offsets.push(pdf.length);
    pdf += `${object}\n`;
  }

  const xrefStart = pdf.length;
  pdf += `xref
0 ${orderedObjects.length + 1}
0000000000 65535 f 
`;

  for (let index = 1; index < offsets.length; index += 1) {
    pdf += `${String(offsets[index]).padStart(10, "0")} 00000 n 
`;
  }

  pdf += `trailer
<< /Size ${orderedObjects.length + 1} /Root 1 0 R >>
startxref
${xrefStart}
%%EOF`;

  return pdf;
}

export function exportRunsAsCsv(runs: GradingRunDetail[]) {
  triggerDownload(buildCsvExport(runs), buildExportFileName("csv", runs.length), "text/csv;charset=utf-8");
}

export function exportRunsAsText(runs: GradingRunDetail[]) {
  triggerDownload(buildTextExport(runs), buildExportFileName("txt", runs.length), "text/plain;charset=utf-8");
}

export function exportRunsAsPdf(runs: GradingRunDetail[]) {
  const text = buildTextExport(runs);
  triggerDownload(buildPdfDocument(text), buildExportFileName("pdf", runs.length), "application/pdf");
}

export function downloadPdfExport(blob: Blob, fileName: string) {
  triggerDownloadBlob(blob, fileName);
}
