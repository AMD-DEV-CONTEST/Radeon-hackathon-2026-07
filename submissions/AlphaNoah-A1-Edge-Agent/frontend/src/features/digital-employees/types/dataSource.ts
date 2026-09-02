import type { DigitalEmployeeCollection } from "./digitalEmployee";

export type DigitalEmployeeReadErrorCode =
  | "unavailable"
  | "transport"
  | "contract"
  | "aborted"
  | "unknown";

export class DigitalEmployeeReadError extends Error {
  readonly code: DigitalEmployeeReadErrorCode;
  readonly source: "mock" | "http";

  constructor(
    code: DigitalEmployeeReadErrorCode,
    source: "mock" | "http",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "DigitalEmployeeReadError";
    this.code = code;
    this.source = source;
  }
}

export interface DigitalEmployeeDataSource {
  readonly source: "mock" | "http";
  getInitialCollection(): DigitalEmployeeCollection | null;
  getEmployees(options?: {
    readonly signal?: AbortSignal;
  }): Promise<DigitalEmployeeCollection>;
}

export type DigitalEmployeeResourceStatus =
  | "idle"
  | "loading"
  | "ready"
  | "refreshing"
  | "error";

export interface DigitalEmployeeResource {
  readonly source: DigitalEmployeeDataSource["source"];
  readonly data: DigitalEmployeeCollection | null;
  readonly status: DigitalEmployeeResourceStatus;
  readonly error: DigitalEmployeeReadError | null;
  refresh(): void;
}
