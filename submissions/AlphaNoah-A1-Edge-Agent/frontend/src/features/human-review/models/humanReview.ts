export type HumanReviewViewState =
  | "pending"
  | "approved"
  | "rejected"
  | "closed"
  | "not_required";

export interface HumanReviewAnalysis {
  readonly finding: string;
  readonly analysis: string;
  readonly recommendation: string | null;
  readonly confidence: number;
  readonly severity: string;
}

export interface HumanReviewTask {
  readonly id: string;
  readonly status: string;
  readonly owner: string;
}

export interface HumanReviewSnapshot {
  readonly eventId: string;
  readonly eventStatus: string;
  readonly state: HumanReviewViewState;
  readonly analysis: HumanReviewAnalysis | null;
  readonly decision: {
    readonly id: string;
    readonly status: string;
    readonly requiresHumanReview: boolean;
  } | null;
  readonly task: HumanReviewTask | null;
  readonly timelineCount: number;
}

export type HumanReviewErrorCode =
  | "transport"
  | "rejected"
  | "contract"
  | "aborted"
  | "unknown";

export class HumanReviewError extends Error {
  readonly code: HumanReviewErrorCode;

  constructor(
    code: HumanReviewErrorCode,
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "HumanReviewError";
    this.code = code;
  }
}

export interface HumanReviewRequest {
  readonly signal?: AbortSignal;
}

export interface HumanReviewDataSource {
  getReview(
    eventId: string,
    request?: HumanReviewRequest,
  ): Promise<HumanReviewSnapshot>;
  approve(
    eventId: string,
    request?: HumanReviewRequest,
  ): Promise<HumanReviewSnapshot>;
  reject(
    eventId: string,
    request?: HumanReviewRequest,
  ): Promise<HumanReviewSnapshot>;
  createTask(
    eventId: string,
    request?: HumanReviewRequest,
  ): Promise<HumanReviewSnapshot>;
}

export type HumanReviewResourceStatus =
  | "idle"
  | "loading"
  | "ready"
  | "submitting"
  | "error";

export interface HumanReviewResource {
  readonly data: HumanReviewSnapshot | null;
  readonly status: HumanReviewResourceStatus;
  readonly error: HumanReviewError | null;
  refresh(): void;
  approve(): Promise<boolean>;
  reject(): Promise<boolean>;
  createTask(): Promise<boolean>;
}
