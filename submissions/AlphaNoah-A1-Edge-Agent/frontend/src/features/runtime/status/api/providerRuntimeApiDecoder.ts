import type {
  ProviderExecutionModeDto,
  ProviderHealthStatusDto,
  ProviderKindDto,
  ProviderRuntimeStatusDto,
  ProviderRuntimeStatusDtoV1,
  ProviderSelectionSourceDto,
} from "./providerRuntimeApiDtos";

type JsonRecord = Record<string, unknown>;

const runtimeStatuses = new Set<ProviderRuntimeStatusDto>([
  "ready",
  "unconfigured",
  "unavailable",
  "invalid_configuration",
  "degraded",
]);
const providerKinds = new Set<ProviderKindDto>([
  "ollama",
  "vllm",
  "openai_compatible",
  "fake",
]);
const executionModes = new Set<ProviderExecutionModeDto>([
  "local",
  "remote",
  "demo",
  "none",
]);
const selectionSources = new Set<ProviderSelectionSourceDto>([
  "command_line",
  "environment",
  "saved_config",
  "injected",
  "none",
]);
const healthStatuses = new Set<ProviderHealthStatusDto>([
  "healthy",
  "synthetic",
  "not_configured",
  "unavailable",
  "invalid_configuration",
  "degraded",
]);

export function decodeProviderRuntimeStatus(
  value: unknown,
): ProviderRuntimeStatusDtoV1 {
  const record = readRecord(value);
  const version = readString(record, "version");
  if (version !== "runtime-status-v1") {
    throw new Error("runtime.version must be runtime-status-v1");
  }

  return {
    version,
    status: readEnum(record, "status", runtimeStatuses),
    provider: readNullableEnum(record, "provider", providerKinds),
    model: readNullableString(record, "model"),
    execution: readEnum(record, "execution", executionModes),
    selection_source: readEnum(
      record,
      "selection_source",
      selectionSources,
    ),
    health: readEnum(record, "health", healthStatuses),
  };
}

function readRecord(value: unknown): JsonRecord {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value)
  ) {
    throw new Error("runtime must be an object");
  }
  return value as JsonRecord;
}

function readString(record: JsonRecord, key: string): string {
  const value = record[key];
  if (typeof value !== "string") {
    throw new Error(`runtime.${key} must be a string`);
  }
  return value;
}

function readNullableString(
  record: JsonRecord,
  key: string,
): string | null {
  const value = record[key];
  if (value === null) {
    return null;
  }
  if (typeof value !== "string") {
    throw new Error(`runtime.${key} must be a string or null`);
  }
  return value;
}

function readEnum<T extends string>(
  record: JsonRecord,
  key: string,
  allowed: ReadonlySet<T>,
): T {
  const value = readString(record, key);
  if (!allowed.has(value as T)) {
    throw new Error(`runtime.${key} is not supported`);
  }
  return value as T;
}

function readNullableEnum<T extends string>(
  record: JsonRecord,
  key: string,
  allowed: ReadonlySet<T>,
): T | null {
  const value = record[key];
  if (value === null) {
    return null;
  }
  if (typeof value !== "string" || !allowed.has(value as T)) {
    throw new Error(`runtime.${key} is not supported`);
  }
  return value as T;
}
