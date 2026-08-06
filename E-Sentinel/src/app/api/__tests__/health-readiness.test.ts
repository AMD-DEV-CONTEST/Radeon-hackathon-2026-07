import { GET } from "../health/route";

jest.mock("@/lib/supabase", () => ({ supabaseAdmin: null }));

describe("GET /api/health", () => {
  it("returns an unconditional liveness response", async () => {
    const response = await GET(new Request("http://localhost:3000/api/health"));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
  });

  it("returns degraded readiness details without turning dependency failure into 500", async () => {
    const response = await GET(new Request("http://localhost:3000/api/health?readiness=true"));
    const body = await response.json();
    expect(response.status).toBe(200);
    expect(body.status).toBe("degraded");
    expect(body.checks).toEqual(expect.objectContaining({
      supabase: expect.objectContaining({ status: "unavailable" }),
      pgvector: expect.objectContaining({ status: "unavailable" }),
      llmProvider: expect.any(Object),
    }));
  });
});
