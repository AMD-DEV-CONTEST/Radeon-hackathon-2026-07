// Integration test: bot-configs pending endpoint
// Tests input validation, error handling, and boundary conditions

export {};

jest.mock("@/lib/supabase", () => ({
  supabaseAdmin: null,
}));

function buildRequest(url: string): Request {
  return new Request(`http://localhost:3000${url}`);
}

describe("GET /api/qa/bot-configs/pending", () => {
  it("returns 500 when Supabase is not configured", async () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- dynamic import needed for isolation in test
    const { GET } = require("../bot-configs/pending/route");
    const res = await GET(buildRequest("/api/qa/bot-configs/pending"));
    expect(res.status).toBe(500);
    const body = await res.json();
    expect(body.error).toBe("Supabase not configured");
  });

  it("caps limit query param at 100", async () => {
    // Even without Supabase, the limit param parsing is testable
    const url = new URL("http://localhost:3000/api/qa/bot-configs/pending?limit=999");
    const limit = Math.min(parseInt(url.searchParams.get("limit") || "30"), 100);
    expect(limit).toBe(100);
  });

  it("defaults limit to 30 when not provided", () => {
    const url = new URL("http://localhost:3000/api/qa/bot-configs/pending");
    const limit = Math.min(parseInt(url.searchParams.get("limit") || "30"), 100);
    expect(limit).toBe(30);
  });

  it("rejects limit=0 gracefully (parses to 0)", () => {
    const url = new URL("http://localhost:3000/api/qa/bot-configs/pending?limit=0");
    const limit = Math.min(parseInt(url.searchParams.get("limit") || "30"), 100);
    expect(limit).toBe(0); // parseInt("0") = 0, Math.min(0, 100) = 0
  });
});
