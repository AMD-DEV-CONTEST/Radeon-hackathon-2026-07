import { afterAll, beforeAll, describe, expect, it } from "vitest";
import request from "supertest";
import type { Express } from "express";
import type { AgentEvent } from "./events.js";
import { createApp, createAppContext, type AppContext } from "./app.js";
import { mockAgentTestConfig } from "./runtime-config.js";

describe("C4 server product API (v2 tools)", () => {
  let app: Express;
  let ctx: AppContext;

  beforeAll(async () => {
    ctx = await createAppContext({ config: mockAgentTestConfig() });
    app = createApp(ctx);
  });

  afterAll(() => {
    ctx.domain.close();
  });

  it("exposes runtime status and day context", async () => {
    const status = await request(app)
      .get("/api/runtime/status")
      .query({ sessionId: "status-test" });
    expect(status.status).toBe(200);
    expect(status.body.providerMode).toBe("local_vllm");

    const day = await request(app).get(
      `/api/households/${status.body.householdId}/day-context`
    );
    expect(day.status).toBe(200);
    expect(day.body.householdIntake.remaining.energyKcal).toBeGreaterThan(0);
    expect(day.body.memberIntake.length).toBe(3);
  });

  it("streams plan via v2 tools and completes meal", async () => {
    const sessionId = "c4-v2-main";
    const plan = await runTurn(
      sessionId,
      "中午我们三个人吃什么？豆腐今天最好吃掉，但我不想再吃鸡腿了。"
    );
    expect(plan.events.some((e) => e.type === "plan_ready")).toBe(true);
    expect(plan.tools).toContain("finalize_meal_plan");
    expect(plan.tools).not.toContain("compose_family_meal");

    const session = await getSession(sessionId);
    expect(session.plan?.version).toBe(1);
    expect(session.state.activePlanId).toBeTruthy();

    // Follow-up that does not finalize again must not re-emit plan_ready.
    const inventory = await runTurn(sessionId, "查看库存");
    expect(inventory.tools).toContain("get_inventory");
    expect(inventory.tools).not.toContain("finalize_meal_plan");
    expect(inventory.events.some((e) => e.type === "plan_ready")).toBe(false);

    const preview = await request(app)
      .post(`/api/households/${ctx.domain.householdId}/meal-complete`)
      .send({ planId: session.state.activePlanId });
    expect(preview.status).toBe(202);
    const conf = preview.body.confirmation;
    const complete = await request(app)
      .post(`/api/pending-actions/${conf.pendingActionId}/confirm`)
      .set("X-PrivatePlate-Session", sessionId)
      .send({
        sessionId,
        confirmationToken: conf.confirmationToken,
        idempotencyKey: `c4-meal-${conf.pendingActionId}`,
        expectedPayloadHash: conf.payloadHash
      });
    expect(complete.status).toBe(200);
    expect(complete.body.ok).toBe(true);

    const day = await request(app).get(
      `/api/households/${ctx.domain.householdId}/day-context`
    );
    expect(day.body.completedMeals.length).toBeGreaterThanOrEqual(1);
  });

  it("blocks medical risk without tools", async () => {
    const sessionId = "medical-risk";
    const result = await runTurn(sessionId, "请根据我的情况调整降糖药剂量");
    expect(result.events.some((e) => e.type === "action_started")).toBe(false);
  });

  it("refuses demo reset while another Agent run is active", async () => {
    const active = ctx.runs.create("reset-guard-session");
    const response = await request(app).post("/api/demo/reset");
    expect(response.status).toBe(409);
    ctx.runs.finish(active.runId, "failed");
  });

  async function runTurn(sessionId: string, text: string) {
    const accepted = await request(app)
      .post("/api/agent/runs")
      .send({ sessionId, text, dinerIds: ["mem-admin", "mem-father", "mem-mother"] });
    expect(accepted.status).toBe(202);
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
      .filter((e): e is Extract<AgentEvent, { type: "action_started" }> => e.type === "action_started")
      .map((e) => e.tool);
    const answer = events
      .filter((e): e is Extract<AgentEvent, { type: "answer_delta" }> => e.type === "answer_delta")
      .map((e) => e.text)
      .join("");
    return { events, tools, answer, runId };
  }

  async function getSession(sessionId: string) {
    const res = await request(app)
      .get(`/api/agent/sessions/${sessionId}`)
      .set("X-PrivatePlate-Session", sessionId);
    return res.body as {
      plan: { version: number } | null;
      state: { activePlanId: string | null };
    };
  }
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
