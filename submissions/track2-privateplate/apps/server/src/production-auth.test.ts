import { afterAll, beforeAll, describe, expect, it } from "vitest";
import request from "supertest";
import type { Express } from "express";
import { createApp, createAppContext, type AppContext } from "./app.js";
import { mockAgentTestConfig } from "./runtime-config.js";

describe("production authentication", () => {
  let app: Express;
  let ctx: AppContext;

  beforeAll(async () => {
    ctx = await createAppContext({
      config: mockAgentTestConfig({
        appMode: "production",
        accessToken: "production-test-token"
      })
    });
    app = createApp(ctx);
  });

  afterAll(() => {
    ctx.domain.close();
  });

  it("protects the web app and API with HTTP Basic auth", async () => {
    const anonymous = await request(app).get("/api/runtime/status");
    expect(anonymous.status).toBe(401);
    expect(anonymous.headers["www-authenticate"]).toContain("Basic");

    const wrong = await request(app)
      .get("/api/runtime/status")
      .auth("privateplate", "wrong-token");
    expect(wrong.status).toBe(401);

    const authorized = await request(app)
      .get("/api/runtime/status")
      .query({ sessionId: "auth-test" })
      .auth("privateplate", "production-test-token");
    expect(authorized.status).toBe(200);
  });
});
