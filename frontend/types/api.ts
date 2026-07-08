export type User = {
  id: string;
  email: string;
  created_at: string;
};

export type AuthPayload = {
  email: string;
  password: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  expires_in_seconds: number;
};

export type CriterionScore = {
  criterion_id: string;
  awarded: number;
  max: number;
  match_type: string;
  verification_status: string;
  feedback: string;
};

export type EvidenceSummary = {
  page: number | null;
  summary: string;
};

export type VisibleEvidenceItem = {
  page: number | null;
  evidence: string;
};

export type QuestionGrade = {
  question_id: string;
  awarded_marks: number;
  max_marks: number;
  feedback: string;
  score_rationale: string;
  correct_elements: string[];
  missing_or_incorrect_elements: string[];
  improvement_suggestions: string[];
  evidence_summaries: EvidenceSummary[];
  visible_evidence: VisibleEvidenceItem[];
  confidence: number | null;
  needs_human_review: boolean;
  criterion_scores: CriterionScore[];
};

export type GradingResult = {
  grading_id: string;
  status: string;
  model_deployment: string;
  total_score: number;
  max_score: number;
  duration_ms: number;
  questions: QuestionGrade[];
};

export type GradingRunStatus = "pending" | "processing" | "completed" | "failed" | "canceled";
export type GradingStage = GradingRunStatus;

export type GradingRunSummary = {
  id: string;
  status: GradingRunStatus;
  stage: GradingStage;
  progress_percent: number;
  status_message: string | null;
  exam_filename: string;
  student_filename: string;
  total_score: number | null;
  max_score: number | null;
  duration_ms: number | null;
  model_deployment: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type GradingRunDetail = {
  id: string;
  status: GradingRunStatus;
  stage: GradingStage;
  progress_percent: number;
  status_message: string | null;
  exam_filename: string;
  student_filename: string;
  total_score: number | null;
  max_score: number | null;
  model_deployment: string | null;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  result: GradingResult | null;
};

export type GradingRunStatusPayload = {
  id: string;
  status: GradingRunStatus;
  stage: GradingStage;
  progress_percent: number;
  status_message: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
};

export type BatchGradingResponse = {
  queue_size: number;
  runs: GradingRunDetail[];
};

export type BulkDeleteResponse = {
  deleted_count: number;
  deleted_ids: string[];
};

export type OverridePayload = {
  question_id: string;
  new_score: number;
  reason: string;
};

export type ApiErrorPayload = {
  detail: string;
  code?: string;
  errors?: unknown;
};
