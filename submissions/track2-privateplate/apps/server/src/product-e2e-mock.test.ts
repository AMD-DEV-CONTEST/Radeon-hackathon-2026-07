/**
 * Product E2E through HTTP + ScriptedProductProvider using protocol v2 only.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import request from "supertest";
import type { Express } from "express";
import { ScriptedProductProvider } from "@privateplate/agent-runtime";
import type { AgentEvent } from "./events.js";
import { createApp, createAppContext, type AppContext } from "./app.js";

describe("HTTP product E2E v2", () => {
  let app: Express;
  let ctx: AppContext;
  const provider = new ScriptedProductProvider();

  beforeAll(async () => {
    ctx = await createAppContext({
      config: {
        appMode: "demo",
        databasePath: ":memory:",
        providerMode: "local_vllm",
        provider,
        model: provider.model,
        baseUrl: "http://127.0.0.1:8000/v1",
        evidenceEligible: false,
        accessToken: null
      }
    });
    app = createApp(ctx);
  });

  afterAll(() => {
    ctx.domain.close();
  });

  it("plan with v2 tools then meal-complete", async () => {
    provider.reset();
    const sessionId = "http-v2-e2e";
    const accepted = await request(app)
      .post("/api/agent/runs")
      .send({
        sessionId,
        text: "规划午餐，不要鸡腿。",
        dinerIds: ["mem-admin", "mem-father", "mem-mother"]
      });
    const runId = String(accepted.body.runId);
    for (let i = 0; i < 200; i += 1) {
      if (ctx.runs.get(runId)?.status !== "running") break;
      await new Promise((r) => setTimeout(r, 5));
    }
    const stream = await request(app)
      .get(`/api/agent/runs/${runId}/events`)
      .query({ sessionId });
    const events = parseEvents(stream.text);
    const tools = events
      .filter(
        (e): e is Extract<AgentEvent, { type: "action_started" }> =>
          e.type === "action_started"
      )
      .map((e) => e.tool);
    expect(tools).toContain("finalize_meal_plan");
    expect(tools).not.toContain("compose_family_meal");

    const session = await request(app)
      .get(`/api/agent/sessions/${sessionId}`)
      .set("X-PrivatePlate-Session", sessionId);
    expect(session.body.state.activePlanId).toBeTruthy();

    const preview = await request(app)
      .post(`/api/households/${ctx.domain.householdId}/meal-complete`)
      .send({ planId: session.body.state.activePlanId });
    expect(preview.status).toBe(202);
    expect(preview.body.status).toBe("preview");
    expect(preview.body.confirmation.pendingActionId).toBeTruthy();

    const complete = await request(app)
      .post(
        `/api/pending-actions/${preview.body.confirmation.pendingActionId}/confirm`
      )
      .set("X-PrivatePlate-Session", sessionId)
      .send({
        sessionId,
        confirmationToken: preview.body.confirmation.confirmationToken,
        idempotencyKey: `e2e-meal-${preview.body.confirmation.pendingActionId}`,
        expectedPayloadHash: preview.body.confirmation.payloadHash
      });
    expect(complete.status).toBe(200);
    expect(complete.body.ok).toBe(true);
  });
});

function parseEvents(text: string): AgentEvent[] {
  const events: AgentEvent[] = [];
  for (const block of text.split("\n\n")) {
    const name = block
      .split("\n")
      .find((l) => l.startsWith("event: "))
      ?.slice("event: ".length);
    const data = block
      .split("\n")
      .filter((l) => l.startsWith("data: "))
      .map((l) => l.slice("data: ".length))
      .join("\n");
    if (!name || name === "stream_end" || !data) continue;
    events.push(JSON.parse(data) as AgentEvent);
  }
  return events;
}
