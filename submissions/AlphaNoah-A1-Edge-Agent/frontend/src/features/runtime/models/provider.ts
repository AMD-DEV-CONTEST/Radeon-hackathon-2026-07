import type { WorkspaceSnapshot } from "./workspaceSnapshot";

export type WorkspaceReadErrorCode =
  | "unavailable"
  | "transport"
  | "contract"
  | "aborted"
  | "unknown";

export class WorkspaceReadError extends Error {
  readonly code: WorkspaceReadErrorCode;
  readonly source: "mock" | "http";

  constructor(
    code: WorkspaceReadErrorCode,
    source: "mock" | "http",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "WorkspaceReadError";
    this.code = code;
    this.source = source;
  }
}

export interface WorkspaceRequest {
  readonly selectedEventId?: string | null;
  readonly signal?: AbortSignal;
}

export interface WorkspaceDataSource {
  readonly source: "mock" | "http";
  getInitialSnapshot(): WorkspaceSnapshot | null;
  getWorkspace(
    request?: WorkspaceRequest,
  ): Promise<WorkspaceSnapshot>;
}

export type WorkspaceResourceStatus =
  | "idle"
  | "loading"
  | "ready"
  | "refreshing"
  | "error";

export interface WorkspaceResource {
  readonly source: WorkspaceDataSource["source"];
  readonly data: WorkspaceSnapshot | null;
  readonly status: WorkspaceResourceStatus;
  readonly error: WorkspaceReadError | null;
  refresh(): void;
}
