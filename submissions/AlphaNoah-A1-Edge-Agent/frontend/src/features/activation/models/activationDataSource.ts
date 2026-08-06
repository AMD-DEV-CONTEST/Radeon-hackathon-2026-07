import type { ActivationSnapshot } from "./activationSnapshot";

export type ActivationErrorCode =
  | "transport"
  | "contract"
  | "rejected"
  | "aborted"
  | "unknown";

export class ActivationError extends Error {
  readonly code: ActivationErrorCode;
  readonly source: "demo-http" | "mock";
  readonly status: number | null;
  readonly eventId: string | null;
  readonly retryable: boolean;

  constructor({
    code,
    source,
    message,
    status = null,
    eventId = null,
    retryable = true,
    cause,
  }: {
    code: ActivationErrorCode;
    source: "demo-http" | "mock";
    message: string;
    status?: number | null;
    eventId?: string | null;
    retryable?: boolean;
    cause?: unknown;
  }) {
    super(message, { cause });
    this.name = "ActivationError";
    this.code = code;
    this.source = source;
    this.status = status;
    this.eventId = eventId;
    this.retryable = retryable;
  }
}

export interface ActivationCommand {
  readonly description: string;
  readonly requestId: string;
  readonly signal?: AbortSignal;
}

export interface ActivationDataSource {
  readonly source: "demo-http" | "mock";
  activate(command: ActivationCommand): Promise<ActivationSnapshot>;
  getEvent(
    eventId: string,
    options?: { readonly signal?: AbortSignal },
  ): Promise<ActivationSnapshot>;
}

export type ActivationResourceStatus =
  | "idle"
  | "activating"
  | "ready"
  | "error";

export interface ActivationResource {
  readonly source: ActivationDataSource["source"];
  readonly snapshot: ActivationSnapshot | null;
  readonly status: ActivationResourceStatus;
  readonly error: ActivationError | null;
  activate(): Promise<void>;
  retry(): Promise<void>;
}
