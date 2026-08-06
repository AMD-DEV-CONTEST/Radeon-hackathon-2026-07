import { POST, GET } from "../qa/diagnosis/route";
import { PATCH } from "../qa/diagnosis/[id]/review/route";
import { authorizeRequest } from "@/lib/api-auth";
import { loadGovernanceContext } from "@/lib/governance/roles";
import { NextResponse } from "next/server";

// ---------------------------------------------------------------------------
// Mocks — jest.mock factories are hoisted; use require() or getter patterns
// ---------------------------------------------------------------------------

jest.mock("@/lib/api-auth", () => ({
  authorizeRequest: jest.fn(),
}));

jest.mock("@/lib/governance/roles", () => ({
  loadGovernanceContext: jest.fn(),
}));

const supabaseMock = { from: jest.fn() };
jest.mock("@/lib/supabase", () => ({
  get supabaseAdmin() {
    return supabaseMock;
  },
}));

const mockedAuth = authorizeRequest as jest.MockedFunction<typeof authorizeRequest>;
const mockedCtx = loadGovernanceContext as jest.MockedFunction<typeof loadGovernanceContext>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockAuthOk() {
  mockedAuth.mockResolvedValue({
    user: { id: "user-1" } as never,
    authType: "bearer",
    role: null,
    error: null,
  });
  mockedCtx.mockResolvedValue({
    userId: "user-1",
    role: "operator",
    dataScope: "all",
    tenantId: "default",
    teamId: null,
    profileName: "Test User",
  });
}

function mockAuthFail() {
  mockedAuth.mockResolvedValue({
    user: null,
    authType: "bearer",
    role: null,
    error: NextResponse.json({ error: "Unauthorized" }, { status: 401 }),
  });
}

// ---------------------------------------------------------------------------
// POST /api/qa/diagnosis
// ---------------------------------------------------------------------------

describe("POST /api/qa/diagnosis", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockAuthOk();
  });

  it("rejects unauthenticated requests", async () => {
    mockAuthFail();
    const req = new Request("http://localhost:3000/api/qa/diagnosis", {
      method: "POST",
      body: JSON.stringify({ conversation_ids: ["c1"] }),
    });
    const res = await POST(req);
    expect(res.status).toBe(401);
  });

  it("rejects empty conversation_ids", async () => {
    const req = new Request("http://localhost:3000/api/qa/diagnosis", {
      method: "POST",
      body: JSON.stringify({ conversation_ids: [] }),
    });
    const res = await POST(req);
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toContain("non-empty");
  });

  it("rejects more than 100 conversation_ids", async () => {
    const ids = Array.from({ length: 101 }, (_, i) => `c${i}`);
    const req = new Request("http://localhost:3000/api/qa/diagnosis", {
      method: "POST",
      body: JSON.stringify({ conversation_ids: ids }),
    });
    const res = await POST(req);
    expect(res.status).toBe(400);
    expect((await res.json()).error).toContain("100");
  });

  it("creates session, runs engine, and returns findings", async () => {
    supabaseMock.from.mockImplementation((table: string) => {
      if (table === "diagnosis_sessions") {
        const chain: Record<string, jest.Mock> = {};
        chain.insert = jest.fn().mockReturnValue(chain);
        chain.select = jest.fn().mockReturnValue(chain);
        chain.single = jest.fn().mockResolvedValue({ data: { id: "sess-1" }, error: null });
        chain.update = jest.fn().mockReturnValue(chain);
        chain.eq = jest.fn().mockResolvedValue({ error: null });
        return chain;
      }
      if (table === "bot_chat_sessions") {
        const chain: Record<string, jest.Mock> = {};
        chain.select = jest.fn().mockReturnValue(chain);
        chain.in = jest.fn().mockReturnValue(chain);
        chain.eq = jest.fn().mockResolvedValue({ data: [], error: null });
        return chain;
      }
      if (table === "diagnosis_findings") {
        return { insert: jest.fn().mockResolvedValue({ error: null }) };
      }
      return {};
    });

    const req = new Request("http://localhost:3000/api/qa/diagnosis", {
      method: "POST",
      body: JSON.stringify({ conversation_ids: ["conv-1", "conv-2"] }),
    });
    const res = await POST(req);
    const body = await res.json();

    expect(res.status).toBe(201);
    expect(body.session_id).toBe("sess-1");
    expect(body.engine_version).toBe("diagnosis-engine-v1.0");
    expect(body.summary).toBeDefined();
    expect(body.summary.roi_claimable).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// GET /api/qa/diagnosis
// ---------------------------------------------------------------------------

describe("GET /api/qa/diagnosis", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockAuthOk();
  });

  it("returns paginated sessions", async () => {
    const sessionsData = [
      { id: "sess-1", status: "completed", created_at: "2026-07-20T10:00:00Z" },
    ];
    supabaseMock.from.mockReturnValue({
      select: jest.fn().mockReturnValue({
        eq: jest.fn().mockReturnValue({
          order: jest.fn().mockReturnValue({
            range: jest.fn().mockResolvedValue({ data: sessionsData, error: null, count: 1 }),
          }),
        }),
      }),
    });

    const req = new Request("http://localhost:3000/api/qa/diagnosis?limit=10&offset=0");
    const res = await GET(req);
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.sessions).toHaveLength(1);
    expect(body.total).toBe(1);
  });

  it("propagates auth failure", async () => {
    mockAuthFail();
    const req = new Request("http://localhost:3000/api/qa/diagnosis");
    const res = await GET(req);
    expect(res.status).toBe(401);
  });
});

// ---------------------------------------------------------------------------
// PATCH /api/qa/diagnosis/[id]/review
// ---------------------------------------------------------------------------

describe("PATCH /api/qa/diagnosis/[id]/review", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockAuthOk();
  });

  const ctx = { params: Promise.resolve({ id: "sess-1" }) };

  it("rejects missing finding_id or decision", async () => {
    const req = new Request("http://localhost:3000/api/qa/diagnosis/sess-1/review", {
      method: "PATCH",
      body: JSON.stringify({ finding_id: "f1" }),
    });
    const res = await PATCH(req, ctx);
    expect(res.status).toBe(400);
  });

  it("rejects invalid decision value", async () => {
    const req = new Request("http://localhost:3000/api/qa/diagnosis/sess-1/review", {
      method: "PATCH",
      body: JSON.stringify({ finding_id: "f1", decision: "maybe" }),
    });
    const res = await PATCH(req, ctx);
    expect(res.status).toBe(400);
  });

  it("returns 404 for finding not in session", async () => {
    supabaseMock.from.mockReturnValue({
      select: jest.fn().mockReturnValue({
        eq: jest.fn().mockReturnValue({
          eq: jest.fn().mockReturnValue({
            eq: jest.fn().mockReturnValue({
              single: jest.fn().mockResolvedValue({ data: null, error: { message: "not found" } }),
            }),
          }),
        }),
      }),
    });

    const req = new Request("http://localhost:3000/api/qa/diagnosis/sess-1/review", {
      method: "PATCH",
      body: JSON.stringify({ finding_id: "f-missing", decision: "accepted" }),
    });
    const res = await PATCH(req, ctx);
    expect(res.status).toBe(404);
  });

  it("saves review and creates work item for accepted finding", async () => {
    let callIndex = 0;
    supabaseMock.from.mockImplementation((table: string) => {
      callIndex++;
      if (table === "diagnosis_findings" && callIndex === 1) {
        const chain: Record<string, jest.Mock> = {};
        chain.select = jest.fn().mockReturnValue(chain);
        chain.eq = jest.fn().mockReturnValue(chain);
        chain.single = jest.fn().mockResolvedValue({
          data: {
            id: "f1",
            session_id: "sess-1",
            tenant_id: "default",
            suggestion: "补充 FAQ",
            reason_category: "inventory_fulfillment",
          },
          error: null,
        });
        return chain;
      }
      if (table === "diagnosis_reviews") {
        const chain: Record<string, jest.Mock> = {};
        chain.insert = jest.fn().mockReturnValue(chain);
        chain.select = jest.fn().mockReturnValue(chain);
        chain.single = jest.fn().mockResolvedValue({
          data: { id: "rev-1", created_at: "2026-07-20T12:00:00Z" },
          error: null,
        });
        return chain;
      }
      if (table === "diagnosis_work_items") {
        const chain: Record<string, jest.Mock> = {};
        chain.insert = jest.fn().mockReturnValue(chain);
        chain.select = jest.fn().mockReturnValue(chain);
        chain.single = jest.fn().mockResolvedValue({
          data: { id: "wi-1", title: "[诊断] inventory_fulfillment: 补充 FAQ", status: "open" },
          error: null,
        });
        return chain;
      }
      return {};
    });

    const req = new Request("http://localhost:3000/api/qa/diagnosis/sess-1/review", {
      method: "PATCH",
      body: JSON.stringify({ finding_id: "f1", decision: "accepted", create_work_item: true }),
    });
    const res = await PATCH(req, ctx);
    const body = await res.json();

    expect(res.status).toBe(201);
    expect(body.review.id).toBe("rev-1");
    expect(body.work_item).toBeDefined();
    expect(body.work_item.id).toBe("wi-1");
  });

  it("does not create work item for rejected findings", async () => {
    let callIndex = 0;
    supabaseMock.from.mockImplementation((table: string) => {
      callIndex++;
      if (table === "diagnosis_findings" && callIndex === 1) {
        const chain: Record<string, jest.Mock> = {};
        chain.select = jest.fn().mockReturnValue(chain);
        chain.eq = jest.fn().mockReturnValue(chain);
        chain.single = jest.fn().mockResolvedValue({
          data: { id: "f2", session_id: "sess-1", tenant_id: "default", suggestion: "x", reason_category: "unknown" },
          error: null,
        });
        return chain;
      }
      if (table === "diagnosis_reviews") {
        const chain: Record<string, jest.Mock> = {};
        chain.insert = jest.fn().mockReturnValue(chain);
        chain.select = jest.fn().mockReturnValue(chain);
        chain.single = jest.fn().mockResolvedValue({
          data: { id: "rev-2", created_at: "2026-07-20T12:00:00Z" },
          error: null,
        });
        return chain;
      }
      return {};
    });

    const req = new Request("http://localhost:3000/api/qa/diagnosis/sess-1/review", {
      method: "PATCH",
      body: JSON.stringify({ finding_id: "f2", decision: "rejected", rejection_reason: "not applicable" }),
    });
    const res = await PATCH(req, ctx);
    const body = await res.json();

    expect(res.status).toBe(201);
    expect(body.review.id).toBe("rev-2");
    expect(body.work_item).toBeNull();
  });
});
