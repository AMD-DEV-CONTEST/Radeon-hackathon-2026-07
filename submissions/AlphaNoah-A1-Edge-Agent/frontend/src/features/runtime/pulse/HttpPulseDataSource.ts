import {
  PulseReadError,
  type PulseDataSource,
  type PulseRequest,
} from "./pulseDataSource";
import {
  adaptPulseProjection,
  decodePulseProjection,
  PulseContractError,
} from "./pulseProjection";

type FetchLike = typeof fetch;

export class HttpPulseDataSource implements PulseDataSource {
  readonly source = "http" as const;

  constructor(
    private readonly fetcher: FetchLike =
      globalThis.fetch.bind(globalThis),
  ) {}

  getInitialPulse(): undefined {
    return undefined;
  }

  async getPulse(request: PulseRequest = {}) {
    if (request.signal?.aborted) {
      throw abortedError();
    }

    let response: Response;
    try {
      response = await this.fetcher("/api/pulse", {
        method: "GET",
        headers: {
          Accept: "application/json",
        },
        cache: "no-store",
        signal: request.signal,
      });
    } catch (error: unknown) {
      if (isAbortError(error, request.signal)) {
        throw abortedError(error);
      }
      throw new PulseReadError(
        "transport",
        this.source,
        "Runtime Pulse is unavailable.",
        { cause: error },
      );
    }

    if (!response.ok) {
      throw new PulseReadError(
        "unavailable",
        this.source,
        "Runtime Pulse request was rejected.",
        { status: response.status },
      );
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error: unknown) {
      if (isAbortError(error, request.signal)) {
        throw abortedError(error);
      }
      throw new PulseReadError(
        "contract",
        this.source,
        "Runtime Pulse returned invalid JSON.",
        { cause: error },
      );
    }

    try {
      const dto = decodePulseProjection(payload);
      return dto === null ? null : adaptPulseProjection(dto);
    } catch (error: unknown) {
      if (error instanceof PulseContractError) {
        throw new PulseReadError(
          "contract",
          this.source,
          "Runtime Pulse response did not match the projection contract.",
          { cause: error },
        );
      }
      throw error;
    }
  }
}

function abortedError(cause?: unknown): PulseReadError {
  return new PulseReadError(
    "aborted",
    "http",
    "Pulse read was aborted.",
    cause === undefined ? {} : { cause },
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
