import { hybridSearch } from "@/lib/hybrid-search";

const mockRpc = jest.fn();
const mockFrom = jest.fn();
const queryEqCalls: unknown[][] = [];
type MockQuery = {
  select: jest.Mock;
  eq: jest.Mock;
  in: jest.Mock;
  then: (resolve: (value: unknown) => unknown, reject: (reason: unknown) => unknown) => Promise<unknown>;
};

jest.mock("@/lib/supabase", () => ({
  supabaseAdmin: {
    rpc: (...args: unknown[]) => mockRpc(...args),
    from: (...args: unknown[]) => mockFrom(...args),
  },
}));

function configureKnowledgeQueries(options?: {
  allowedIds?: string[];
  entries?: Array<Record<string, unknown>>;
}) {
  const allowedIds = options?.allowedIds ?? ["entry-a"];
  const entries = options?.entries ?? [{
    id: "entry-a",
    title: "Tenant A",
    content: "Scoped content",
    category: "faq",
    keywords: [],
  }];
  mockFrom.mockImplementation(() => {
    const query = {} as MockQuery;
    let selected = "";
    query.select = jest.fn((value: string) => {
      selected = value;
      return query;
    });
    query.eq = jest.fn((...args: unknown[]) => {
      queryEqCalls.push(args);
      return query;
    });
    query.in = jest.fn(() => query);
    query.then = (resolve: (value: unknown) => unknown, reject: (reason: unknown) => unknown) =>
      Promise.resolve({
        data:
          selected === "id"
            ? allowedIds.map((id) => ({ id }))
            : entries,
        error: null,
      }).then(resolve, reject);
    return query;
  });
}

describe("HybridSearch tenant scope", () => {
  beforeEach(() => {
    mockRpc.mockReset();
    mockFrom.mockReset();
    queryEqCalls.length = 0;
  });

  test("fails closed without a tenant and does not call the RPC", async () => {
    await expect(hybridSearch("shipping status")).resolves.toEqual({
      matches: [],
      method: "none",
      total: 0,
    });
    expect(mockRpc).not.toHaveBeenCalled();
  });

  test("passes the tenant into both SQL RPC calls", async () => {
    configureKnowledgeQueries();
    mockRpc.mockResolvedValue({
      data: [{
        id: "entry-a",
        title: "Tenant A",
        content: "Scoped content",
        category: "faq",
        keywords: [],
        similarity: 0.9,
      }],
      error: null,
    });

    const result = await hybridSearch("shipping status", { tenantId: "tenant-a" });

    expect(result.matches.map((match) => match.id)).toEqual(["entry-a"]);
    expect(queryEqCalls).toEqual(expect.arrayContaining([
      ["tenant_id", "tenant-a"],
      ["status", "published"],
    ]));
    expect(mockRpc).toHaveBeenNthCalledWith(1, "hybrid_search_vector", expect.objectContaining({
      tenant_id: "tenant-a",
    }));
    expect(mockRpc).toHaveBeenNthCalledWith(2, "hybrid_search_keyword", expect.objectContaining({
      tenant_id: "tenant-a",
    }));
  });

  test("filters cross-tenant RPC rows before merging", async () => {
    configureKnowledgeQueries({
      allowedIds: ["entry-a"],
      entries: [{
        id: "entry-a",
        title: "Tenant A",
        content: "Scoped content",
        category: "faq",
        keywords: [],
      }],
    });
    mockRpc.mockResolvedValue({
      data: [
        { id: "entry-a", title: "Tenant A", content: "A", category: "faq", keywords: [], similarity: 0.9 },
        { id: "entry-b", title: "Tenant B", content: "B", category: "faq", keywords: [], similarity: 0.95 },
      ],
      error: null,
    });

    const result = await hybridSearch("shipping status", { tenantId: "tenant-a" });

    expect(result.matches.map((match) => match.id)).toEqual(["entry-a"]);
  });

  test("applies threshold before choosing a fallback method and scopes final lookup", async () => {
    configureKnowledgeQueries();
    mockRpc.mockImplementation((name: string) => Promise.resolve({
      data: [{
        id: "entry-a",
        title: "Tenant A",
        content: "Scoped content",
        category: "faq",
        keywords: [],
        similarity: name === "hybrid_search_vector" ? 0.9 : 0.1,
      }],
      error: null,
    }));

    const result = await hybridSearch("shipping status", {
      tenantId: "tenant-a",
      threshold: 0.5,
    });

    expect(result.method).toBe("vector_only");
    expect(result.matches).toHaveLength(1);
  });
});
