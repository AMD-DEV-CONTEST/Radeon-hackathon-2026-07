import type {
  ProviderRuntimeDataSource,
  ProviderRuntimeRequest,
  ProviderRuntimeSnapshot,
} from "../models/providerRuntime";

export const mockProviderRuntimeSnapshot: ProviderRuntimeSnapshot = {
  source: "mock",
  contractVersion: "runtime-status-v1",
  visibility: "ready",
  runtimeStatus: "ready",
  provider: "ollama",
  model: "qwen3.5:9b",
  execution: "local",
  selectionSource: "saved_config",
  health: "healthy",
};

export class MockProviderRuntimeDataSource
  implements ProviderRuntimeDataSource
{
  readonly source = "mock" as const;

  constructor(
    private readonly snapshot: ProviderRuntimeSnapshot =
      mockProviderRuntimeSnapshot,
  ) {}

  getInitialSnapshot(): ProviderRuntimeSnapshot {
    return this.snapshot;
  }

  async getRuntimeStatus(
    request: ProviderRuntimeRequest = {},
  ): Promise<ProviderRuntimeSnapshot> {
    if (request.signal?.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }
    return this.snapshot;
  }
}

export const mockProviderRuntimeDataSource =
  new MockProviderRuntimeDataSource();
