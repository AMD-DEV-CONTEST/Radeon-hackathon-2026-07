import { POST } from "../qa/events/route";
import { authorizeRequest } from "@/lib/api-auth";
import { ingestEvidenceEvent } from "@/lib/governance/event-store";
import { loadGovernanceContext } from "@/lib/governance/roles";

jest.mock("@/lib/api-auth", () => ({
  authorizeRequest: jest.fn(),
}));
jest.mock("@/lib/governance/event-store", () => ({
  ingestEvidenceEvent: jest.fn(),
}));
jest.mock("@/lib/governance/roles", () => ({
  loadGovernanceContext: jest.fn(),
}));

const mockedAuthorizeRequest = authorizeRequest as jest.MockedFunction<typeof authorizeRequest>;
const mockedIngestEvidenceEvent = ingestEvidenceEvent as jest.MockedFunction<typeof ingestEvidenceEvent>;
const mockedLoadGovernanceContext = loadGovernanceContext as jest.MockedFunction<typeof loadGovernanceContext>;

function request(body: Record<string, unknown>, headers?: Record<string, string>): Request {
  return new Request("http://localhost:3000/api/qa/events", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

describe("POST /api/qa/events", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedAuthorizeRequest.mockResolvedValue({
      user: { id: "user-1" } as never,
      authType: "bearer",
      role: null,
      error: null,
    });
    mockedLoadGovernanceContext.mockResolvedValue({
      userId: "user-1",
      role: "operator",
      dataScope: "team",
      tenantId: "tenant-a",
      teamId: "team-a",
      profileName: "Operator",
    });
    mockedIngestEvidenceEvent.mockResolvedValue({ status: "accepted", event_id: "event-1" });
  });

  it("rejects an authenticated user without a tenant context", async () => {
    mockedLoadGovernanceContext.mockResolvedValue(null);

    const response = await POST(request({
      id: "event-1",
      source: "mock",
      type: "commerce.event.v1",
      time: "2026-07-23T00:00:00.000Z",
      tenant_id: "tenant-a",
      data: {},
    }));

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ error: "Authenticated user has no tenant context" });
    expect(mockedIngestEvidenceEvent).not.toHaveBeenCalled();
  });

  it("rejects cross-tenant events before persistence", async () => {
    const response = await POST(request({
      id: "event-1",
      source: "mock",
      type: "commerce.event.v1",
      time: "2026-07-23T00:00:00.000Z",
      tenant_id: "tenant-b",
      data: {},
    }));

    expect(response.status).toBe(403);
    expect(mockedIngestEvidenceEvent).not.toHaveBeenCalled();
  });

  it("propagates the W3C traceparent and overwrites the actor from auth context", async () => {
    const traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
    const response = await POST(request({
      id: "event-1",
      source: "mock",
      type: "commerce.event.v1",
      time: "2026-07-23T00:00:00.000Z",
      tenant_id: "tenant-a",
      actor: { id: "spoofed", type: "system" },
      data: {},
    }, { traceparent }));

    expect(response.status).toBe(202);
    expect(mockedIngestEvidenceEvent).toHaveBeenCalledWith(expect.objectContaining({
      tenant_id: "tenant-a",
      traceparent,
      actor: { id: "user-1", type: "user", name: "Operator" },
    }));
  });
});
