import type { EvidenceSummary, VisibleEvidenceItem } from "@/types/api";

function normalize(text: string) {
  return text.replace(/\s+/g, " ").trim().toLowerCase();
}

export function hasDistinctEvidenceSummaries(
  visibleEvidence: VisibleEvidenceItem[],
  evidenceSummaries: EvidenceSummary[],
) {
  if (evidenceSummaries.length === 0) {
    return false;
  }
  const visibleKeys = new Set(
    visibleEvidence.map((item) => `${item.page ?? "none"}:${normalize(item.evidence)}`),
  );
  return evidenceSummaries.some((item) => !visibleKeys.has(`${item.page ?? "none"}:${normalize(item.summary)}`));
}
