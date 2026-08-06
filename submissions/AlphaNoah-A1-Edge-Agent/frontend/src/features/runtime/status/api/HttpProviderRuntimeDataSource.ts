import { adaptProviderRuntimeStatus } from "../adapter/providerRuntimeAdapter";
import {
  ProviderRuntimeReadError,
  type ProviderRuntimeDataSource,
  type ProviderRuntimeRequest,
  type ProviderRuntimeSnapshot,
} from "../models/providerRuntime";
import { decodeProviderRuntimeStatus } from "./providerRuntimeApiDecoder";

type FetchLike = typeof fetch;

export class HttpProviderRuntimeDataSource
  implements ProviderRuntimeDataSource
{
  readonly source = "http" as const;

  constructor(
    private readonly fetcher: FetchLike =
      globalThis.fetch.bind(globalThis),
  ) {}

  getInitialSnapshot(): ProviderRuntimeSnapshot | null {
    return null;
  }

  async getRuntimeStatus(
    request: ProviderRuntimeRequest = {},
  ): Promise<ProviderRuntimeSnapshot> {
    if (request.signal?.aborted) {
      throw abortedError();
    }

    let response: Response;
    try {
      response = await this.fetcher("/api/runtime", {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: request.signal,
      });
    } catch (error: unknown) {
      if (isAbortError(error, request.signal)) {
        throw abortedError(error);
      }
      throw new ProviderRuntimeReadError(
        "transport",
        this.source,
        "AI Runtime status is unreachable.",
        { cause: error },
      );
    }

    if (!response.ok) {
      throw new ProviderRuntimeReadError(
        "unavailable",
        this.source,
        "AI Runtime status request was rejected.",
      );
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error: unknown) {
      if (isAbortError(error, request.signal)) {
        throw abortedError(error);
      }
      throw new ProviderRuntimeReadError(
        "contract",
        this.source,
        "AI Runtime status returned invalid JSON.",
        { cause: error },
      );
    }

    try {
      return adaptProviderRuntimeStatus(
        decodeProviderRuntimeStatus(payload),
        this.source,
      );
    } catch (error: unknown) {
      throw new ProviderRuntimeReadError(
        "contract",
        this.source,
        "AI Runtime status did not match runtime-status-v1.",
        { cause: error },
      );
    }
  }
}

function abortedError(cause?: unknown): ProviderRuntimeReadError {
  return new ProviderRuntimeReadError(
    "aborted",
    "http",
    "AI Runtime status read was aborted.",
    cause === undefined ? undefined : { cause },
  );
}

function isAbortError(
  error: unknown,
  signal?: AbortSignal,
): boolean {
  return (
    signal?.aborted === true ||
    (error instanceof DOMException && error.name === "AbortError")
  );
}
