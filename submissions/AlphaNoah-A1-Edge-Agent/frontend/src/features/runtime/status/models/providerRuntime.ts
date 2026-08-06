import type {
  ProviderExecutionModeDto,
  ProviderHealthStatusDto,
  ProviderKindDto,
  ProviderRuntimeStatusDto,
  ProviderSelectionSourceDto,
} from "../api/providerRuntimeApiDtos";

export type ProviderRuntimeVisibility = "ready" | "unavailable";

export interface ProviderRuntimeSnapshot {
  readonly source: "http" | "mock";
  readonly contractVersion: "runtime-status-v1";
  readonly visibility: ProviderRuntimeVisibility;
  readonly runtimeStatus: ProviderRuntimeStatusDto;
  readonly provider: ProviderKindDto | null;
  readonly model: string | null;
  readonly execution: ProviderExecutionModeDto;
  readonly selectionSource: ProviderSelectionSourceDto;
  readonly health: ProviderHealthStatusDto;
}

export type ProviderRuntimeReadErrorCode =
  | "transport"
  | "unavailable"
  | "contract"
  | "aborted"
  | "unknown";

export class ProviderRuntimeReadError extends Error {
  readonly code: ProviderRuntimeReadErrorCode;
  readonly source: ProviderRuntimeDataSource["source"];

  constructor(
    code: ProviderRuntimeReadErrorCode,
    source: ProviderRuntimeDataSource["source"],
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ProviderRuntimeReadError";
    this.code = code;
    this.source = source;
  }
}

export interface ProviderRuntimeRequest {
  readonly signal?: AbortSignal;
}

export interface ProviderRuntimeDataSource {
  readonly source: "http" | "mock";
  getInitialSnapshot(): ProviderRuntimeSnapshot | null;
  getRuntimeStatus(
    request?: ProviderRuntimeRequest,
  ): Promise<ProviderRuntimeSnapshot>;
}

export type ProviderRuntimeResourceStatus =
  | "idle"
  | "loading"
  | "ready"
  | "refreshing"
  | "error";

export interface ProviderRuntimeResource {
  readonly source: ProviderRuntimeDataSource["source"];
  readonly data: ProviderRuntimeSnapshot | null;
  readonly status: ProviderRuntimeResourceStatus;
  readonly error: ProviderRuntimeReadError | null;
  refresh(): void;
}
