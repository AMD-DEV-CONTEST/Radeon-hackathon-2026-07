import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RoleAssignmentPanel } from "../RoleAssignmentPanel";

const { getRoleAssignmentsMock, getOllamaModelsMock, setRoleAssignmentsMock } = vi.hoisted(() => ({
  getRoleAssignmentsMock: vi.fn(),
  getOllamaModelsMock: vi.fn(),
  setRoleAssignmentsMock: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  getRoleAssignments: getRoleAssignmentsMock,
  getOllamaModels: getOllamaModelsMock,
  setRoleAssignments: setRoleAssignmentsMock,
}));

describe("RoleAssignmentPanel", () => {
  beforeEach(() => {
    getRoleAssignmentsMock.mockResolvedValue({
      oracle: "determinex/planner",
      architect: "cloud/claude-best",
      builder: "ollama/qwen2.5-coder:7b-instruct",
      monitor: "cloud/gpt4o",
    });
    getOllamaModelsMock.mockResolvedValue([
      {
        id: "qwen2.5-coder:7b-instruct",
        name: "qwen2.5-coder:7b-instruct",
        size_gb: 4.4,
        param_size: "7B",
        is_determinex: false,
      },
    ]);
    setRoleAssignmentsMock.mockResolvedValue(undefined);
  });

  it("labels cloud choices with provider readiness so users can pick intentionally", async () => {
    render(<RoleAssignmentPanel keyStatus={{ anthropic: true, openai: false }} />);

    await waitFor(() => expect(screen.getByText("Hybrid Slot Stack")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Claude Opus 4.8"));

    expect(screen.getAllByText("Connected").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Needs key").length).toBeGreaterThan(0);
    expect(screen.getAllByText("OpenAI / GPT-4o").length).toBeGreaterThan(0);
  });

  it("saves free cloud, keyed cloud, and local role choices through the same assignment contract", async () => {
    render(<RoleAssignmentPanel keyStatus={{ anthropic: true, openrouter: true }} />);

    await waitFor(() => expect(screen.getByText("Hybrid Slot Stack")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Claude Opus 4.8"));
    fireEvent.click(screen.getByText("Qwen3 Coder 480B"));
    fireEvent.click(screen.getByText("Save Slots"));

    await waitFor(() => {
      expect(setRoleAssignmentsMock).toHaveBeenCalledWith(
        expect.objectContaining({ architect: "free/qwen3-coder" })
      );
    });
  });
});
