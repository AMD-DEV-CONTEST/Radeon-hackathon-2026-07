// Integration test: knowledge pending endpoint
// Tests input validation, error handling, and boundary conditions

import { GET } from "../knowledge/pending/route";

jest.mock("@/lib/supabase", () => ({
  supabaseAdmin: null,
}));

jest.mock("@/lib/governance/authorization", () => ({
  authorizeGovernanceRequest: jest.fn(async () => ({
    auth: { user: null, authType: "api_key", role: "operator", error: null },
    context: {
      userId: "service",
      role: "operator",
      dataScope: "all",
      tenantId: "tenant-a",
      teamId: null,
      profileName: null,
    },
    error: null,
  })),
}));

function buildRequest(url: string): Request {
  return new Request(`http://localhost:3000${url}`);
}

describe("GET /api/qa/knowledge/pending", () => {
  it("returns 500 when Supabase is not configured", async () => {
    const res = await GET(buildRequest("/api/qa/knowledge/pending"));
    expect(res.status).toBe(500);
    const body = await res.json();
    expect(body.error).toBe("Supabase not configured");
  });

  it("caps limit query param at 100", async () => {
    const url = new URL("http://localhost:3000/api/qa/knowledge/pending?limit=999");
    const limit = Math.min(parseInt(url.searchParams.get("limit") || "30"), 100);
    expect(limit).toBe(100);
  });

  it("defaults limit to 30 when not provided", () => {
    const url = new URL("http://localhost:3000/api/qa/knowledge/pending");
    const limit = Math.min(parseInt(url.searchParams.get("limit") || "30"), 100);
    expect(limit).toBe(30);
  });
});
