import { describe, expect, it, vi } from "vitest";

import { HttpHumanReviewDataSource } from "./HttpHumanReviewDataSource";

const eventId = "event_0123456789abcdef0123456789abcdef";
const decisionId = "decision_0123456789abcdef0123456789abcdef";
const taskId = "task_0123456789abcdef0123456789abcdef";

describe("HttpHumanReviewDataSource", () => {
  it("reads Event, Task, and safe timeline projections", async () => {
    const fetcher = vi.fn(fetchHarness("pending"));
    const source = new HttpHumanReviewDataSource(fetcher);

    const snapshot = await source.getReview(eventId);

    expect(snapshot.state).toBe("pending");
    expect(snapshot.analysis).toMatchObject({
      finding: "Room A08 air conditioner remained on",
      recommendation: "Verify occupancy, then use the approved shutdown procedure",
      confidence: 0.85,
    });
    expect(snapshot.timelineCount).toBe(2);
    expect(JSON.stringify(snapshot)).not.toMatch(
      /do-not-expose|hidden-from-view|private-audit|C:\\runtime/,
    );
    expect(requests(fetcher)).toEqual([
      `GET /api/events/${eventId}`,
      `GET /api/events/${eventId}/task`,
      `GET /api/events/${eventId}/timeline`,
    ]);
  });

  it("waits for Review, Task, and refreshed Runtime reads on approval", async () => {
    const fetcher = vi.fn(fetchHarness("approve"));
    const source = new HttpHumanReviewDataSource(fetcher);

    const snapshot = await source.approve(eventId);

    expect(snapshot.state).toBe("approved");
    expect(snapshot.task).toMatchObject({ id: taskId, status: "CREATED" });
    expect(requests(fetcher)).toEqual([
      `POST /api/events/${eventId}/review`,
      `POST /api/events/${eventId}/task`,
      `GET /api/events/${eventId}`,
      `GET /api/events/${eventId}/task`,
      `GET /api/events/${eventId}/timeline`,
    ]);
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      action: "approve",
      comment: "Approved in the AlphaNoah Human Review panel.",
    });
  });

  it("records rejection without issuing a Task command", async () => {
    const fetcher = vi.fn(fetchHarness("reject"));
    const source = new HttpHumanReviewDataSource(fetcher);

    const snapshot = await source.reject(eventId);

    expect(snapshot.state).toBe("rejected");
    expect(snapshot.task).toBeNull();
    expect(requests(fetcher)).not.toContain(
      `POST /api/events/${eventId}/task`,
    );
  });

  it("returns a bounded error when Runtime rejects a request", async () => {
    const fetcher = vi.fn(async () =>
      jsonResponse(
        { error_code: "INVALID_REQUEST", message: "Rejected." },
        409,
      ),
    );
    const source = new HttpHumanReviewDataSource(fetcher);

    await expect(source.getReview(eventId)).rejects.toMatchObject({
      code: "rejected",
      message: "Human review request was rejected (INVALID_REQUEST).",
    });
  });
});

function fetchHarness(mode: "pending" | "approve" | "reject") {
  let state: "pending" | "approved" | "rejected" = "pending";
  return async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const url = requestUrl(input);
    const method = init?.method ?? "GET";

    if (method === "POST" && url.endsWith("/review")) {
      state = mode === "reject" ? "rejected" : "approved";
      return jsonResponse({
        event_id: eventId,
        status: state === "rejected" ? "REJECTED" : "APPROVED",
        human_review_id:
          "human_review_0123456789abcdef0123456789abcdef",
        outcome: state === "rejected" ? "REJECTED" : "APPROVED",
        decision_id: decisionId,
      });
    }
    if (method === "POST" && url.endsWith("/task")) {
      return jsonResponse(taskPayload(true));
    }
    if (url === `/api/events/${eventId}`) {
      return jsonResponse(eventPayload(state));
    }
    if (url === `/api/events/${eventId}/task`) {
      return jsonResponse(taskPayload(state === "approved"));
    }
    if (url === `/api/events/${eventId}/timeline`) {
      return jsonResponse(timelinePayload(state));
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  };
}

function eventPayload(state: "pending" | "approved" | "rejected") {
  return {
    prompt: "do-not-expose",
    trace_id: "do-not-expose",
    local_path: "C:\\runtime\\private.sqlite3",
    event_id: eventId,
    status:
      state === "pending"
        ? "PENDING_HUMAN_REVIEW"
        : state === "approved"
          ? "TASK_CREATED"
          : "REJECTED",
    skill_id: "restaurant-aircon-shutdown",
    skill_version: "1.0-demo",
    analysis: {
      detected_issue: "Room A08 air conditioner remained on",
      decision_type: "ai_assisted_incident_analysis",
      reasoning_summary: "No occupancy was reported after closing.",
      evidence: [
        "evidence_used=synthetic report",
        "suggested_human_action=Verify occupancy, then use the approved shutdown procedure",
      ],
      model_or_rule: "hidden-from-view",
      confidence: 0.85,
      requires_human_review: true,
      severity: "HIGH",
    },
    decision: {
      decision_id: decisionId,
      status:
        state === "pending"
          ? "PENDING_HUMAN_REVIEW"
          : state === "approved"
            ? "APPROVED"
            : "REJECTED",
      requires_human_review: true,
    },
  };
}

function taskPayload(hasTask: boolean) {
  return {
    event_id: eventId,
    task: hasTask
      ? {
          task_id: taskId,
          status: "CREATED",
          owner: "demo:restaurant-duty-operator",
        }
      : null,
  };
}

function timelinePayload(state: "pending" | "approved" | "rejected") {
  return [
    {
      sequence: 1,
      timestamp: "2026-08-01T10:00:00+08:00",
      action: "event_created",
      entity_type: "Event",
      entity_id: eventId,
      status: "NEW",
    },
    {
      sequence: 2,
      timestamp: "2026-08-01T10:01:00+08:00",
      action:
        state === "pending" ? "human_review_requested" : "human_decision_applied",
      audit_details: "private-audit",
      request_id: "do-not-expose",
      entity_type: "Decision",
      entity_id: decisionId,
      status:
        state === "pending" ? "PENDING_HUMAN_REVIEW" : state.toUpperCase(),
    },
  ];
}

function requests(fetcher: ReturnType<typeof vi.fn>): readonly string[] {
  return fetcher.mock.calls.map(([input, init]) => {
    const method = (init as RequestInit | undefined)?.method ?? "GET";
    return `${method} ${requestUrl(input as RequestInfo | URL)}`;
  });
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") {
    return input;
  }
  return input instanceof URL ? input.pathname : new URL(input.url).pathname;
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
