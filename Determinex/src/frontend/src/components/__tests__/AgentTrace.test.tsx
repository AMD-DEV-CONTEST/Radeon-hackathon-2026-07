import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { AgentTrace } from "../AgentTrace";
import * as api from "../../lib/api";

vi.mock("../../lib/api", () => ({
  invokeSafe: vi.fn(),
  isTauri: vi.fn(() => true),
  listHiveSessions: vi.fn(() =>
    Promise.resolve([
      {
        session_id: "mock-session-1",
        status: "active",
        spec_path: "mock/path",
        lang: "python",
        budget: 10,
        steps: [],
      },
    ])
  ),
}));

describe("AgentTrace component", () => {
  beforeEach(() => {
    (api.invokeSafe as any).mockImplementation(async (cmd: string) => {
      return null;
    });
  });

  it("renders AgentTrace session view and control buttons", async () => {
    render(<AgentTrace />);

    await waitFor(() => {
      expect(screen.getByText(/Agent Job Queue/i)).toBeInTheDocument();
    });
  });
});
