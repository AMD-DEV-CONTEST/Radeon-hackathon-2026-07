import type { PulseNotice } from "../models";

export type PulseReadErrorCode =
  | "unavailable"
  | "transport"
  | "contract"
  | "aborted"
  | "unknown";

export class PulseReadError extends Error {
  readonly code: PulseReadErrorCode;
  readonly source: "mock" | "http";
  readonly status: number | null;

  constructor(
    code: PulseReadErrorCode,
    source: "mock" | "http",
    message: string,
    options: ErrorOptions & { readonly status?: number | null } = {},
  ) {
    super(message, options);
    this.name = "PulseReadError";
    this.code = code;
    this.source = source;
    this.status = options.status ?? null;
  }
}

export interface PulseRequest {
  readonly signal?: AbortSignal;
}

export interface PulseDataSource {
  readonly source: "mock" | "http";
  /**
   * `undefined` means no read has completed. `null` is a confirmed idle
   * projection from the selected source.
   */
  getInitialPulse(): PulseNotice | null | undefined;
  getPulse(request?: PulseRequest): Promise<PulseNotice | null>;
}

export type PulseResourceStatus =
  | "idle"
  | "loading"
  | "ready"
  | "refreshing"
  | "error";

export interface PulseResource {
  readonly source: PulseDataSource["source"];
  readonly notice: PulseNotice | null;
  readonly status: PulseResourceStatus;
  readonly error: PulseReadError | null;
  refresh(): void;
}
