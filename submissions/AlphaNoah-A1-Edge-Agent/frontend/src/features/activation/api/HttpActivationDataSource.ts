import { adaptActivationSnapshot } from "../adapter/activationAdapter";
import {
  ActivationError,
  type ActivationCommand,
  type ActivationDataSource,
  type ActivationSnapshot,
} from "../models";
import {
  decodeActivationError,
  decodeActivationResponse,
  ActivationContractError,
} from "./activationApiDecoders";
import {
  DEMO_ACTIVATION_SCENARIO,
  type DemoActivationRequestDto,
} from "./activationApiDtos";

type FetchLike = typeof fetch;

export class HttpActivationDataSource
  implements ActivationDataSource
{
  readonly source = "demo-http" as const;

  constructor(
    private readonly fetcher: FetchLike =
      globalThis.fetch.bind(globalThis),
  ) {}

  async activate(
    command: ActivationCommand,
  ): Promise<ActivationSnapshot> {
    const body: DemoActivationRequestDto = {
      scenario_id: DEMO_ACTIVATION_SCENARIO,
      description: command.description,
      request_id: command.requestId,
    };
    return this.request("/api/demo/events", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      signal: command.signal,
    });
  }

  async getEvent(
    eventId: string,
    options?: { readonly signal?: AbortSignal },
  ): Promise<ActivationSnapshot> {
    return this.request(
      `/api/demo/events/${encodeURIComponent(eventId)}`,
      {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: options?.signal,
      },
    );
  }

  private async request(
    url: string,
    init: RequestInit,
  ): Promise<ActivationSnapshot> {
    let response: Response;
    try {
      response = await this.fetcher(url, init);
    } catch (error: unknown) {
      if (
        error instanceof DOMException &&
        error.name === "AbortError"
      ) {
        throw new ActivationError({
          code: "aborted",
          source: this.source,
          message: "Activation request was aborted.",
          retryable: false,
          cause: error,
        });
      }
      throw new ActivationError({
        code: "transport",
        source: this.source,
        message: "Activation service is unavailable.",
        cause: error,
      });
    }

    const payload = await readJson(response);
    if (!response.ok) {
      const controlled = decodeActivationError(payload);
      throw new ActivationError({
        code: "rejected",
        source: this.source,
        message:
          controlled?.message ??
          "Activation service rejected the request.",
        status: response.status,
        eventId: controlled?.event_id ?? null,
        retryable: response.status >= 500 || Boolean(controlled?.event_id),
      });
    }

    try {
      return adaptActivationSnapshot(
        decodeActivationResponse(payload),
        this.source,
      );
    } catch (error: unknown) {
      if (error instanceof ActivationContractError) {
        throw new ActivationError({
          code: "contract",
          source: this.source,
          message: "Activation response did not match the contract.",
          status: response.status,
          retryable: false,
          cause: error,
        });
      }
      throw error;
    }
  }
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch (error: unknown) {
    throw new ActivationError({
      code: "contract",
      source: "demo-http",
      message: "Activation service returned invalid JSON.",
      status: response.status,
      retryable: false,
      cause: error,
    });
  }
}
