import {
  parseH3ProductProjection,
  type H3ProductProjection,
} from "./h3Projection";

export type ResearchStatus =
  | "not_started"
  | "queued"
  | "resolving"
  | "searching"
  | "reading"
  | "extracting"
  | "synthesizing"
  | "ready"
  | "insufficient"
  | "retryable_failed"
  | "failed";

const ACTIVE_RESEARCH_STATUSES: ReadonlySet<ResearchStatus> = new Set([
  "not_started",
  "queued",
  "resolving",
  "searching",
  "reading",
  "extracting",
  "synthesizing",
]);

export function isActiveResearchStatus(status: ResearchStatus): boolean {
  return ACTIVE_RESEARCH_STATUSES.has(status);
}

export type JobStatus =
  | "queued"
  | "researching"
  | "scripting"
  | "rendering"
  | "voicing"
  | "composing"
  | "succeeded"
  | "failed";

export const STEVE_JOBS_IMPORTED_REFERENCE_SHA256 =
  "fe82d64b5c47c2ef9159428f7dc1bedc18bf90dfe4ff86dff551672bbc673153";

export interface GpuRuntimeProof {
  phase: "flux" | "h3";
  promptId: string;
  queueId: number;
  submissionNonce: string;
  workflowSha256: string;
  gpuActivityObserved: boolean;
  processExited: boolean;
  referenceSha256: string | null;
  referenceSourceMode: "preuploaded_imported";
}

export interface BookIdentity {
  id: string;
  title: string;
  author?: string;
  language?: string;
  edition?: string;
  translator?: string;
}

export interface DiscoveryCandidate {
  candidateId: string;
  title: string;
  author: string;
  language: string;
  edition: string;
  translator: string;
}

export interface DirectionSummary {
  id: string;
  directionKey: string;
  score: number;
  payload: Record<string, unknown>;
  momentNumber?: number;
  summary?: string;
  keywords?: string[];
  resonanceOptions?: ResonanceOption[];
}

export interface ResonanceOption {
  id: string;
  text: string;
}

export interface BookSummary extends BookIdentity {
  researchStatus: ResearchStatus;
  evidenceCoverage: Record<string, unknown>;
  contentMode?: "source_grounded" | "ai_completed";
  directions: DirectionSummary[];
  momentCount?: number;
  shelfHook?: string;
}

export type ResolveInputResult = {
  resolutionId: string;
  resolution: "candidates" | "unresolved";
  candidates: DiscoveryCandidate[];
};

export interface SelectCandidateResult {
  book: BookIdentity;
  researchJobId: string;
}

export interface PreviewShot {
  ordinal: number;
  narrativeTask: string;
  action: string;
  stateTransition: string;
  durationSeconds: number;
}

export interface DirectorPreview {
  bookId: string;
  directionRevisionId: string;
  scriptRevisionId: string;
  provisionalTitle: string;
  experiencePromise: string;
  openingLine: string;
  openingLineKind: string;
  openingLineLabel: string;
  contentMode: "source_grounded" | "ai_completed";
  contentLabel: string;
  contentNotice: string;
  emotionCurve: string[];
  shots: PreviewShot[];
  durationEstimateSeconds: number;
  fitFor: string[];
  notFitFor: string[];
  sourceSummaries: unknown[];
  spoilerLevel: string;
  riskFlags: string[];
  customQuestion?: string;
}

export interface DeliveryArtifacts {
  video: string;
  subtitle?: string;
  cover?: string;
  shareCard?: string;
}

export interface VideoJob {
  jobId: string;
  bookId: string;
  status: JobStatus;
  contentMode?: "source_grounded" | "ai_completed";
  contentLabel?: string;
  contentNotice?: string;
  artifacts?: DeliveryArtifacts;
  h3Product?: H3ProductProjection;
  gpuRuntimeProof?: GpuRuntimeProof;
  error?: { error_code?: string; message?: string; retryable?: boolean };
}

type VideoJobWire = Omit<VideoJob, "h3Product" | "gpuRuntimeProof"> & {
  h3Product?: unknown;
  gpuRuntimeProof?: unknown;
};

export interface FeedbackInput {
  bookId: string;
  directionRevisionId: string;
  resonanceText: string;
  jobId?: string;
  momentRevisionId?: string;
  resonanceOptionId?: string;
  wantsToRead?: boolean;
  spoilerJudgment: "acceptable" | "too_much" | "none";
  comment?: string;
}

export interface ShiduClient {
  resolveInput(title: string, signal?: AbortSignal): Promise<ResolveInputResult>;
  selectCandidate(resolutionId: string, candidateId: string, signal?: AbortSignal): Promise<SelectCandidateResult>;
  retryResearch(bookId: string, signal?: AbortSignal): Promise<SelectCandidateResult>;
  listShelf(signal?: AbortSignal): Promise<{ books: BookSummary[] }>;
  listBooks(signal?: AbortSignal): Promise<{ books: BookSummary[] }>;
  getBook(bookId: string, signal?: AbortSignal): Promise<{ book: BookSummary }>;
  directorPreview(
    input: { bookId: string; directionRevisionId: string; customQuestion?: string },
    signal?: AbortSignal,
  ): Promise<DirectorPreview>;
  createVideoJob(
    input: { bookId: string; directionRevisionId: string; trialScriptRevisionId: string },
    signal?: AbortSignal,
  ): Promise<VideoJob>;
  getVideoJob(jobId: string, signal?: AbortSignal): Promise<VideoJob>;
  sendFeedback(input: FeedbackInput, signal?: AbortSignal): Promise<{ feedbackId: string; accepted: true }>;
}

interface PublicError {
  error_code: string;
  message: string;
  retryable: boolean;
}

export class ShiduApiError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly status: number;

  constructor(status: number, payload: PublicError) {
    super(payload.message);
    this.name = "ShiduApiError";
    this.status = status;
    this.code = payload.error_code;
    this.retryable = payload.retryable;
  }
}

function idempotencyKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

async function readJson<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T | PublicError;
  if (!response.ok) {
    const error = payload as Partial<PublicError>;
    throw new ShiduApiError(response.status, {
      error_code: error.error_code ?? "unexpected_response",
      message: error.message ?? "服务返回了无法识别的错误",
      retryable: error.retryable === true,
    });
  }
  return payload as T;
}

export function createShiduClient(fetchImpl: typeof fetch = fetch): ShiduClient {
  const retryKeys = new Map<string, string>();

  async function request<T>(
    path: string,
    init: RequestInit = {},
    idempotent = false,
  ): Promise<T> {
    if (!path.startsWith("/api/") || path.includes("://")) {
      throw new Error("Shidu API requests must be same-origin");
    }
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
    if (idempotent) headers.set("Idempotency-Key", idempotencyKey());
    return readJson<T>(await fetchImpl(path, { ...init, headers }));
  }

  async function retryableCommand<T>(
    path: string,
    payload: Record<string, string>,
    signal?: AbortSignal,
  ): Promise<T> {
    const body = JSON.stringify(payload);
    const fingerprint = `${path}\n${body}`;
    const key = retryKeys.get(fingerprint) ?? idempotencyKey();
    retryKeys.set(fingerprint, key);
    try {
      const result = await request<T>(path, {
        method: "POST",
        body,
        signal,
        headers: { "Idempotency-Key": key },
      });
      retryKeys.delete(fingerprint);
      return result;
    } catch (error) {
      if (error instanceof ShiduApiError && !error.retryable) {
        retryKeys.delete(fingerprint);
      }
      throw error;
    }
  }

  function parseGpuRuntimeProof(value: unknown): GpuRuntimeProof {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new Error("Invalid GPU runtime proof");
    }
    const proof = value as Record<string, unknown>;
    const expected = [
      "gpuActivityObserved",
      "phase",
      "processExited",
      "promptId",
      "queueId",
      "referenceSha256",
      "referenceSourceMode",
      "submissionNonce",
      "workflowSha256",
    ];
    const digest = /^[0-9a-f]{64}$/;
    const nonce = /^[0-9a-f]{32}$/;
    const keys = Object.keys(proof).sort();
    const phase = proof.phase;
    const referenceSha256 = proof.referenceSha256;
    if (
      keys.length !== expected.length
      || keys.some((key, index) => key !== expected[index])
      || (phase !== "flux" && phase !== "h3")
      || typeof proof.promptId !== "string"
      || proof.promptId.length < 1
      || proof.promptId.length > 200
      || !Number.isSafeInteger(proof.queueId)
      || Number(proof.queueId) < 0
      || typeof proof.submissionNonce !== "string"
      || !nonce.test(proof.submissionNonce)
      || typeof proof.workflowSha256 !== "string"
      || !digest.test(proof.workflowSha256)
      || typeof proof.gpuActivityObserved !== "boolean"
      || typeof proof.processExited !== "boolean"
      || proof.referenceSourceMode !== "preuploaded_imported"
      || (phase === "flux" && referenceSha256 !== null)
      || (phase === "h3" && referenceSha256 !== STEVE_JOBS_IMPORTED_REFERENCE_SHA256)
    ) {
      throw new Error("Invalid GPU runtime proof");
    }
    return proof as unknown as GpuRuntimeProof;
  }

  function parseVideoJobWire(wire: VideoJobWire): VideoJob {
    const { h3Product, gpuRuntimeProof, ...job } = wire;
    if (gpuRuntimeProof !== undefined && job.status !== "rendering") {
      throw new Error("Invalid GPU runtime proof");
    }
    return {
      ...job,
      ...(h3Product === undefined
        ? {}
        : { h3Product: parseH3ProductProjection(h3Product) }),
      ...(gpuRuntimeProof === undefined
        ? {}
        : { gpuRuntimeProof: parseGpuRuntimeProof(gpuRuntimeProof) }),
    };
  }

  async function readVideoJob(
    path: string,
    init: RequestInit,
    idempotent = false,
  ): Promise<VideoJob> {
    const wire = await request<VideoJobWire>(path, init, idempotent);
    return parseVideoJobWire(wire);
  }

  return {
    resolveInput: (title, signal) =>
      retryableCommand("/api/resolve-input", { title }, signal),
    selectCandidate: (resolutionId, candidateId, signal) =>
      retryableCommand(
        `/api/resolve-input/${encodeURIComponent(resolutionId)}/select`,
        { candidateId },
        signal,
      ),
    retryResearch: (bookId, signal) =>
      retryableCommand(
        `/api/books/${encodeURIComponent(bookId)}/research`,
        {},
        signal,
      ),
    listShelf: (signal) => request("/api/shelf", { signal }),
    listBooks: (signal) => request("/api/books", { signal }),
    getBook: (bookId, signal) =>
      request(`/api/books/${encodeURIComponent(bookId)}`, { signal }),
    directorPreview: (input, signal) =>
      request("/api/director-preview", { method: "POST", body: JSON.stringify(input), signal }, true),
    createVideoJob: async (input, signal) =>
      parseVideoJobWire(
        await retryableCommand<VideoJobWire>(
          "/api/video-jobs",
          input,
          signal,
        ),
      ),
    getVideoJob: (jobId, signal) =>
      readVideoJob(`/api/video-jobs/${encodeURIComponent(jobId)}`, { signal }),
    sendFeedback: (input, signal) =>
      request("/api/feedback", { method: "POST", body: JSON.stringify(input), signal }, true),
  };
}
