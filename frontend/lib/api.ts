import { clearAccessToken, getAccessToken } from "@/lib/auth";
import type {
  ApiErrorPayload,
  AuthPayload,
  BatchGradingResponse,
  BulkDeleteResponse,
  GradingResult,
  GradingRunDetail,
  GradingRunStatusPayload,
  GradingRunSummary,
  OverridePayload,
  TokenResponse,
  User
} from "@/types/api";

export class ApiError extends Error {
  status: number;
  code?: string;
  errors?: unknown;

  constructor(payload: ApiErrorPayload, status: number) {
    super(payload.detail || "Request failed");
    this.name = "ApiError";
    this.status = status;
    this.code = payload.code;
    this.errors = payload.errors;
  }
}

type RequestOptions = RequestInit & {
  authenticated?: boolean;
};

type BlobResponse = {
  blob: Blob;
  fileName: string | null;
};

function getApiBaseUrl() {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api").replace(/\/+$/, "");
}

function buildUrl(path: string) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${getApiBaseUrl()}${normalizedPath}`;
}

function buildHeaders(options: RequestOptions): Headers {
  const headers = new Headers(options.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (options.authenticated) {
    const token = getAccessToken();
    if (!token) {
      throw new ApiError({ detail: "You must be logged in to continue", code: "missing_token" }, 401);
    }
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

async function parseError(response: Response): Promise<ApiError> {
  const payload = (await response.json().catch(() => null)) as ApiErrorPayload | null;
  return new ApiError(
    payload ?? {
      detail: response.statusText || "Request failed",
      code: "request_failed"
    },
    response.status
  );
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(buildUrl(path), {
    ...options,
    headers: buildHeaders(options)
  });

  if (!response.ok) {
    const error = await parseError(response);
    if (response.status === 401 && options.authenticated) {
      clearAccessToken();
    }
    throw error;
  }

  return response.json() as Promise<T>;
}

function parseContentDispositionFileName(header: string | null) {
  if (!header) {
    return null;
  }
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) {
    return decodeURIComponent(utf8Match[1]);
  }
  const plainMatch = header.match(/filename="([^"]+)"/i) ?? header.match(/filename=([^;]+)/i);
  return plainMatch ? plainMatch[1].trim() : null;
}

async function requestBlob(path: string, options: RequestOptions = {}): Promise<BlobResponse> {
  const response = await fetch(buildUrl(path), {
    ...options,
    headers: buildHeaders(options)
  });

  if (!response.ok) {
    const error = await parseError(response);
    if (response.status === 401 && options.authenticated) {
      clearAccessToken();
    }
    throw error;
  }

  return {
    blob: await response.blob(),
    fileName: parseContentDispositionFileName(response.headers.get("Content-Disposition"))
  };
}

export function getErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed";
}

export function isBackgroundNetworkError(error: unknown) {
  return error instanceof TypeError && error.message.toLowerCase().includes("fetch");
}

export const api = {
  register(payload: AuthPayload) {
    return request<User>("/auth/register", {
      body: JSON.stringify(payload),
      method: "POST"
    });
  },
  login(payload: AuthPayload) {
    return request<TokenResponse>("/auth/login", {
      body: JSON.stringify(payload),
      method: "POST"
    });
  },
  me() {
    return request<User>("/auth/me", { authenticated: true });
  },
  listGradings() {
    return request<GradingRunSummary[]>("/gradings", { authenticated: true });
  },
  getGrading(id: string) {
    return request<GradingRunDetail>(`/gradings/${id}`, { authenticated: true });
  },
  getGradingStatus(id: string) {
    return request<GradingRunStatusPayload>(`/gradings/${id}/status`, { authenticated: true });
  },
  submitGrading({
    examPdf,
    studentPdf
  }: {
    examPdf: File;
    studentPdf: File;
  }) {
    const formData = new FormData();
    formData.append("exam_pdf", examPdf);
    formData.append("student_pdf", studentPdf);
    return request<GradingRunDetail>("/gradings", {
      authenticated: true,
      body: formData,
      method: "POST"
    });
  },
  submitBatchGrading({
    examPdf,
    studentPdfs
  }: {
    examPdf: File;
    studentPdfs: File[];
  }) {
    const formData = new FormData();
    formData.append("exam_pdf", examPdf);
    studentPdfs.forEach((file) => formData.append("student_pdfs", file));
    return request<BatchGradingResponse>("/gradings/batch", {
      authenticated: true,
      body: formData,
      method: "POST"
    });
  },
  overrideGrade(id: string, payload: OverridePayload) {
    return request(`/gradings/${id}/override`, {
      authenticated: true,
      body: JSON.stringify(payload),
      method: "PATCH"
    });
  },
  cancelGrading(id: string) {
    return request<{ grading_id: string; status: string; canceled_at: string }>(`/gradings/${id}/cancel`, {
      authenticated: true,
      method: "PATCH"
    });
  },
  deleteGradings(gradingIds: string[]) {
    return request<BulkDeleteResponse>("/gradings", {
      authenticated: true,
      body: JSON.stringify({ grading_ids: gradingIds }),
      method: "DELETE"
    });
  },
  exportGradingsPdf(gradingIds: string[]) {
    return requestBlob("/gradings/export", {
      authenticated: true,
      body: JSON.stringify({ grading_ids: gradingIds }),
      headers: {
        Accept: "application/pdf, application/json"
      },
      method: "POST"
    });
  }
};

export type {
  AuthPayload,
  BatchGradingResponse,
  BulkDeleteResponse,
  GradingResult,
  GradingRunDetail,
  GradingRunStatusPayload,
  GradingRunSummary,
  OverridePayload,
  TokenResponse,
  User
} from "@/types/api";
