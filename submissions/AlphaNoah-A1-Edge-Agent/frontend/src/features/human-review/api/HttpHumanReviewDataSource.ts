import {
  decodeRuntimeApiError,
  decodeRuntimeEventDetail,
  decodeRuntimeTask,
  decodeRuntimeTimeline,
} from "../../runtime/api/runtimeApiDecoders";
import { adaptHumanReviewSnapshot } from "../adapter/humanReviewAdapter";
import {
  HumanReviewError,
  type HumanReviewDataSource,
  type HumanReviewRequest,
  type HumanReviewSnapshot,
} from "../models/humanReview";
import { decodeHumanReviewCommand } from "./humanReviewApiDecoders";

type FetchLike = typeof fetch;

const eventIdPattern = /^event_[a-f0-9]{32}$/;

export class HttpHumanReviewDataSource
  implements HumanReviewDataSource
{
  constructor(
    private readonly fetcher: FetchLike =
      globalThis.fetch.bind(globalThis),
  ) {}

  async getReview(
    eventId: string,
    request: HumanReviewRequest = {},
  ): Promise<HumanReviewSnapshot> {
    this.validateEventId(eventId);
    const encodedId = encodeURIComponent(eventId);
    const [eventPayload, taskPayload, timelinePayload] =
      await Promise.all([
        this.requestJson(`/api/events/${encodedId}`, {
          method: "GET",
          signal: request.signal,
        }),
        this.requestJson(`/api/events/${encodedId}/task`, {
          method: "GET",
          signal: request.signal,
        }),
        this.requestJson(`/api/events/${encodedId}/timeline`, {
          method: "GET",
          signal: request.signal,
        }),
      ]);

    try {
      return adaptHumanReviewSnapshot(
        decodeRuntimeEventDetail(eventPayload),
        decodeRuntimeTask(taskPayload),
        decodeRuntimeTimeline(timelinePayload),
      );
    } catch (error: unknown) {
      if (error instanceof HumanReviewError) {
        throw error;
      }
      throw new HumanReviewError(
        "contract",
        "Human review responses did not match the Runtime contract.",
        { cause: error },
      );
    }
  }

  async approve(
    eventId: string,
    request: HumanReviewRequest = {},
  ): Promise<HumanReviewSnapshot> {
    await this.submitReview(eventId, "approve", request);
    await this.createTaskCommand(eventId, request);
    return this.getReview(eventId, request);
  }

  async reject(
    eventId: string,
    request: HumanReviewRequest = {},
  ): Promise<HumanReviewSnapshot> {
    await this.submitReview(eventId, "reject", request);
    return this.getReview(eventId, request);
  }

  async createTask(
    eventId: string,
    request: HumanReviewRequest = {},
  ): Promise<HumanReviewSnapshot> {
    await this.createTaskCommand(eventId, request);
    return this.getReview(eventId, request);
  }

  private async submitReview(
    eventId: string,
    action: "approve" | "reject",
    request: HumanReviewRequest,
  ): Promise<void> {
    this.validateEventId(eventId);
    const payload = await this.requestJson(
      `/api/events/${encodeURIComponent(eventId)}/review`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          comment:
            action === "approve"
              ? "Approved in the AlphaNoah Human Review panel."
              : "Rejected in the AlphaNoah Human Review panel.",
        }),
        signal: request.signal,
      },
    );
    const decoded = decodeHumanReviewCommand(payload);
    if (decoded.event_id !== eventId) {
      throw new HumanReviewError(
        "contract",
        "Human review response referenced another Event.",
      );
    }
  }

  private async createTaskCommand(
    eventId: string,
    request: HumanReviewRequest,
  ): Promise<void> {
    this.validateEventId(eventId);
    const payload = await this.requestJson(
      `/api/events/${encodeURIComponent(eventId)}/task`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        signal: request.signal,
      },
    );
    const decoded = decodeRuntimeTask(payload);
    if (decoded.event_id !== eventId || decoded.task === null) {
      throw new HumanReviewError(
        "contract",
        "Task command did not return the Event Task.",
      );
    }
  }

  private async requestJson(
    url: string,
    init: RequestInit,
  ): Promise<unknown> {
    if (init.signal?.aborted) {
      throw abortedError();
    }

    let response: Response;
    try {
      response = await this.fetcher(url, {
        ...init,
        headers: {
          Accept: "application/json",
          ...(init.headers ?? {}),
        },
        cache: "no-store",
      });
    } catch (error: unknown) {
      if (isAbortError(error, init.signal)) {
        throw abortedError(error);
      }
      throw new HumanReviewError(
        "transport",
        "Human review Runtime is unreachable.",
        { cause: error },
      );
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error: unknown) {
      if (isAbortError(error, init.signal)) {
        throw abortedError(error);
      }
      throw new HumanReviewError(
        "contract",
        "Human review Runtime returned invalid JSON.",
        { cause: error },
      );
    }

    if (!response.ok) {
      let publicCode = "REQUEST_REJECTED";
      try {
        publicCode = decodeRuntimeApiError(payload).error_code;
      } catch {
        // The UI still receives a bounded generic error below.
      }
      throw new HumanReviewError(
        "rejected",
        `Human review request was rejected (${publicCode}).`,
      );
    }

    return payload;
  }

  private validateEventId(eventId: string): void {
    if (!eventIdPattern.test(eventId)) {
      throw new HumanReviewError(
        "contract",
        "Human review requires a valid Runtime Event ID.",
      );
    }
  }
}

function abortedError(cause?: unknown): HumanReviewError {
  return new HumanReviewError(
    "aborted",
    "Human review request was aborted.",
    cause === undefined ? undefined : { cause },
  );
}

function isAbortError(
  error: unknown,
  signal?: AbortSignal | null,
): boolean {
  return (
    signal?.aborted === true ||
    (error instanceof DOMException && error.name === "AbortError")
  );
}
