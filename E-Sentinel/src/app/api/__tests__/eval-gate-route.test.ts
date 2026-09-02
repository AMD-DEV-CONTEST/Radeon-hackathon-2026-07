import { NextResponse } from "next/server";
import { GET } from "../qa/eval-gate/route";
import { authorizeRequest } from "@/lib/api-auth";

jest.mock("@/lib/api-auth", () => ({
  authorizeRequest: jest.fn(),
}));

const mockedAuthorizeRequest = authorizeRequest as jest.MockedFunction<typeof authorizeRequest>;

describe("GET /api/qa/eval-gate", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedAuthorizeRequest.mockResolvedValue({
      user: null,
      authType: "api_key",
      role: "viewer",
      error: null,
    });
  });

  it("returns fixture-only baseline/candidate comparison", async () => {
    const response = await GET(new Request("http://localhost:3000/api/qa/eval-gate"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.fixture_only).toBe(true);
    expect(body.production_execution).toBe("not_connected");
    expect(body.case_count).toBe(15);
    expect(body.baseline.passed).toBe(false);
    expect(body.candidate.passed).toBe(true);
    expect(body.comparison).toEqual({ passed: true, regressions: [] });
  });

  it("supports selecting the safety set and validates bad set values", async () => {
    const safetyResponse = await GET(new Request("http://localhost:3000/api/qa/eval-gate?set=safety"));
    const safetyBody = await safetyResponse.json();
    expect(safetyResponse.status).toBe(200);
    expect(safetyBody.selected_set).toBe("safety");
    expect(safetyBody.case_count).toBe(4);

    const badResponse = await GET(new Request("http://localhost:3000/api/qa/eval-gate?set=unknown"));
    expect(badResponse.status).toBe(400);
  });

  it("keeps authentication failures fail-closed", async () => {
    mockedAuthorizeRequest.mockResolvedValue({
      user: null,
      authType: "api_key",
      role: null,
      error: NextResponse.json({ error: "Unauthorized" }, { status: 401 }),
    });

    const response = await GET(new Request("http://localhost:3000/api/qa/eval-gate"));
    expect(response.status).toBe(401);
  });
});
