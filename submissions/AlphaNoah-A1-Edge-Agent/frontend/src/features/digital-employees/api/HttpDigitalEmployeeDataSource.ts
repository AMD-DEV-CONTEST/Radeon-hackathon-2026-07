import {
  adaptDigitalEmployeeCollection,
} from "../adapter/digitalEmployeeAdapter";
import {
  DigitalEmployeeReadError,
  type DigitalEmployeeCollection,
  type DigitalEmployeeDataSource,
} from "../types";
import {
  decodeDigitalEmployeeProjection,
  DigitalEmployeeContractError,
} from "./digitalEmployeeApiDecoders";

type FetchLike = typeof fetch;

export class HttpDigitalEmployeeDataSource
  implements DigitalEmployeeDataSource
{
  readonly source = "http" as const;

  constructor(
    private readonly fetcher: FetchLike =
      globalThis.fetch.bind(globalThis),
  ) {}

  getInitialCollection(): DigitalEmployeeCollection | null {
    return null;
  }

  async getEmployees(options?: {
    readonly signal?: AbortSignal;
  }): Promise<DigitalEmployeeCollection> {
    const signal = options?.signal;
    if (signal?.aborted) {
      throw abortedError();
    }

    let response: Response;
    try {
      response = await this.fetcher("/api/digital-employees", {
        method: "GET",
        headers: {
          Accept: "application/json",
        },
        cache: "no-store",
        signal,
      });
    } catch (error: unknown) {
      if (
        signal?.aborted ||
        (error instanceof DOMException && error.name === "AbortError")
      ) {
        throw abortedError(error);
      }
      throw new DigitalEmployeeReadError(
        "transport",
        this.source,
        "Digital employee projection is unreachable.",
        { cause: error },
      );
    }

    if (!response.ok) {
      throw new DigitalEmployeeReadError(
        "unavailable",
        this.source,
        "Digital employee projection is unavailable.",
      );
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error: unknown) {
      throw new DigitalEmployeeReadError(
        "contract",
        this.source,
        "Digital employee projection returned invalid JSON.",
        { cause: error },
      );
    }

    try {
      return adaptDigitalEmployeeCollection(
        decodeDigitalEmployeeProjection(payload),
      );
    } catch (error: unknown) {
      if (error instanceof DigitalEmployeeContractError) {
        throw new DigitalEmployeeReadError(
          "contract",
          this.source,
          "Digital employee projection did not match the contract.",
          { cause: error },
        );
      }
      throw error;
    }
  }
}

function abortedError(cause?: unknown): DigitalEmployeeReadError {
  return new DigitalEmployeeReadError(
    "aborted",
    "http",
    "Digital employee projection read was aborted.",
    cause === undefined ? undefined : { cause },
  );
}
