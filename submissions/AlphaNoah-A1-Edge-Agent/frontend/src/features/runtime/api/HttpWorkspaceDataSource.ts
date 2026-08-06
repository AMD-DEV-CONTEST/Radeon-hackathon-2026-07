import {
  WorkspaceReadError,
  type WorkspaceDataSource,
  type WorkspaceRequest,
  type WorkspaceSnapshot,
} from "../models";
import {
  adaptWorkspaceProjection,
} from "../adapter/workspaceProjectionAdapter";
import { decodeRuntimeWorkspaceProjection } from "./runtimeApiDecoders";

type FetchLike = typeof fetch;

export class HttpWorkspaceDataSource implements WorkspaceDataSource {
  readonly source = "http" as const;

  constructor(
    private readonly fetcher: FetchLike =
      globalThis.fetch.bind(globalThis),
  ) {}

  getInitialSnapshot(): WorkspaceSnapshot | null {
    return null;
  }

  async getWorkspace(
    request: WorkspaceRequest = {},
  ): Promise<WorkspaceSnapshot> {
    if (request.signal?.aborted) {
      throw abortedError();
    }

    let response: Response;
    try {
      response = await this.fetcher("/api/workspace", {
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
      throw new WorkspaceReadError(
        "transport",
        this.source,
        "Runtime workspace is unavailable.",
        { cause: error },
      );
    }

    if (!response.ok) {
      throw new WorkspaceReadError(
        "unavailable",
        this.source,
        "Runtime workspace request was rejected.",
      );
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error: unknown) {
      if (isAbortError(error, request.signal)) {
        throw abortedError(error);
      }
      throw new WorkspaceReadError(
        "contract",
        this.source,
        "Runtime workspace returned invalid JSON.",
        { cause: error },
      );
    }

    try {
      return adaptWorkspaceProjection(
        decodeRuntimeWorkspaceProjection(payload),
      );
    } catch (error: unknown) {
      if (error instanceof WorkspaceReadError) {
        throw error;
      }
      throw new WorkspaceReadError(
        "contract",
        this.source,
        "Runtime workspace response did not match workspace-v1.",
        { cause: error },
      );
    }
  }
}

function abortedError(cause?: unknown): WorkspaceReadError {
  return new WorkspaceReadError(
    "aborted",
    "http",
    "Workspace read was aborted.",
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
