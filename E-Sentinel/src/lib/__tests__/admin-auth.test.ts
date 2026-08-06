describe("admin auth", () => {
  jest.mock("@/lib/supabase", () => ({ supabaseAdmin: null }));
  jest.mock("@/lib/correlation", () => ({ createCorrelationId: () => "test-correlation-id" }));

  const originalEnv = process.env;

  beforeEach(() => {
    jest.resetModules();
    process.env = { ...originalEnv };
    delete process.env.ADMIN_API_KEY;
    delete process.env.ADMIN_VIEWER_KEY;
    delete process.env.API_SECRET;
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  function request(key?: string): Request {
    return new Request("http://localhost:3000/api/admin/shadow-approval", {
      headers: key ? { "x-api-key": key } : undefined,
    });
  }

  it("accepts API_SECRET as the local operator key when ADMIN_API_KEY is absent", async () => {
    process.env.API_SECRET = "local-secret";

    const { authenticateAdmin } = await import("@/lib/admin-auth");
    const result = await authenticateAdmin(request("local-secret"));

    expect(result.error).toBeNull();
    expect(result.role).toBe("operator");
  });

  it("still returns 503 when no operator key is configured", async () => {
    const { authenticateAdmin } = await import("@/lib/admin-auth");
    const result = await authenticateAdmin(request("anything"));

    expect(result.role).toBeNull();
    expect(result.error?.status).toBe(503);
  });

  it("prevents viewer keys from performing mutations", async () => {
    process.env.API_SECRET = "operator-secret";
    process.env.ADMIN_VIEWER_KEY = "viewer-secret";

    const { requireOperator } = await import("@/lib/admin-auth");
    const result = await requireOperator(request("viewer-secret"));

    expect(result.role).toBeNull();
    expect(result.error?.status).toBe(403);
  });
});
