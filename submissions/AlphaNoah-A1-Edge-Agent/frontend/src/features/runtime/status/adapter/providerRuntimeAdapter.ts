import type { ProviderRuntimeStatusDtoV1 } from "../api/providerRuntimeApiDtos";
import type {
  ProviderRuntimeDataSource,
  ProviderRuntimeSnapshot,
} from "../models/providerRuntime";

export function adaptProviderRuntimeStatus(
  dto: ProviderRuntimeStatusDtoV1,
  source: ProviderRuntimeDataSource["source"],
): ProviderRuntimeSnapshot {
  return {
    source,
    contractVersion: dto.version,
    visibility: dto.status === "ready" ? "ready" : "unavailable",
    runtimeStatus: dto.status,
    provider: dto.provider,
    model: dto.model,
    execution: dto.execution,
    selectionSource: dto.selection_source,
    health: dto.health,
  };
}
