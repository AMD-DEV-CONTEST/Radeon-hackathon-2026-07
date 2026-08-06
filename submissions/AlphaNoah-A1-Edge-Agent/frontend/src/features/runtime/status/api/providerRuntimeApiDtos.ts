export type ProviderRuntimeStatusDto =
  | "ready"
  | "unconfigured"
  | "unavailable"
  | "invalid_configuration"
  | "degraded";

export type ProviderKindDto =
  | "ollama"
  | "vllm"
  | "openai_compatible"
  | "fake";

export type ProviderExecutionModeDto =
  | "local"
  | "remote"
  | "demo"
  | "none";

export type ProviderSelectionSourceDto =
  | "command_line"
  | "environment"
  | "saved_config"
  | "injected"
  | "none";

export type ProviderHealthStatusDto =
  | "healthy"
  | "synthetic"
  | "not_configured"
  | "unavailable"
  | "invalid_configuration"
  | "degraded";

export interface ProviderRuntimeStatusDtoV1 {
  readonly version: "runtime-status-v1";
  readonly status: ProviderRuntimeStatusDto;
  readonly provider: ProviderKindDto | null;
  readonly model: string | null;
  readonly execution: ProviderExecutionModeDto;
  readonly selection_source: ProviderSelectionSourceDto;
  readonly health: ProviderHealthStatusDto;
}
