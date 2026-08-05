import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { ExecutionWorkspace } from "../ExecutionWorkspace";

const { isTauriMock, listHiveSessionsMock, checkOllamaStatusMock, checkDockerStatusMock } =
  vi.hoisted(() => ({
    isTauriMock: vi.fn(() => true),
    listHiveSessionsMock: vi.fn(),
    checkOllamaStatusMock: vi.fn(),
    checkDockerStatusMock: vi.fn(),
  }));

vi.mock("@/lib/api", () => ({
  isTauri: isTauriMock,
  listHiveSessions: listHiveSessionsMock,
  checkOllamaStatus: checkOllamaStatusMock,
  checkDockerStatus: checkDockerStatusMock,
}));

const SESSION = (overrides: Partial<Record<string, unknown>> = {}) => ({
  session_id: "4f615ba9-17a3-479b-9ae6-ec5497932eb6",
  lang: "rust",
  project_name: "Unnamed Project",
  status: "in_progress" as const,
  step_count: 4,
  complete_count: 2,
  failed_count: 0,
  created_at: "2026-07-27T03:24:24Z",
  updated_at: "2026-07-27T03:24:24Z",
  project_root: "C:\\Users\\ryang\\AppData\\Local\\Temp\\determinex_workspaces\\4f615ba9",
  ...overrides,
});

describe("ExecutionWorkspace (Runtime addon)", () => {
  beforeEach(() => {
    isTauriMock.mockReset().mockReturnValue(true);
    listHiveSessionsMock.mockReset().mockResolvedValue([]);
    checkOllamaStatusMock.mockReset().mockResolvedValue({ ok: false, error: "not reachable" });
    checkDockerStatusMock
      .mockReset()
      .mockResolvedValue({ running: false, version: "", message: "Docker is not installed." });
  });

  it("shows the browser-mode message and never calls the backend when not in Tauri", async () => {
    isTauriMock.mockReturnValue(false);
    render(<ExecutionWorkspace />);
    expect(screen.getByText("Browser mode cannot read live runtime state")).toBeInTheDocument();
    expect(listHiveSessionsMock).not.toHaveBeenCalled();
    expect(checkOllamaStatusMock).not.toHaveBeenCalled();
    expect(checkDockerStatusMock).not.toHaveBeenCalled();
  });

  it("shows an honest empty state when no sessions are running", async () => {
    listHiveSessionsMock.mockResolvedValue([SESSION({ status: "complete" })]);
    render(<ExecutionWorkspace />);
    await waitFor(() => {
      expect(screen.getByText("No hive sessions currently running.")).toBeInTheDocument();
    });
  });

  it("lists only in_progress sessions, not complete/failed/pending ones", async () => {
    listHiveSessionsMock.mockResolvedValue([
      SESSION({ session_id: "running-1", project_name: "Running One", status: "in_progress" }),
      SESSION({ session_id: "done-1", project_name: "Done One", status: "complete" }),
      SESSION({ session_id: "failed-1", project_name: "Failed One", status: "failed" }),
    ]);
    render(<ExecutionWorkspace />);
    await waitFor(() => {
      expect(screen.getByText("Running One")).toBeInTheDocument();
    });
    expect(screen.queryByText("Done One")).not.toBeInTheDocument();
    expect(screen.queryByText("Failed One")).not.toBeInTheDocument();
    expect(screen.getByText("2/4")).toBeInTheDocument();
  });

  it("reflects real Ollama and Docker status, not a fake always-online state", async () => {
    checkOllamaStatusMock.mockResolvedValue({ ok: true });
    checkDockerStatusMock.mockResolvedValue({
      running: false,
      version: "",
      message: "Docker is installed but not running. Start Docker Desktop, then retry.",
    });
    render(<ExecutionWorkspace />);
    await waitFor(() => {
      expect(screen.getByText("Ollama")).toBeInTheDocument();
    });
    expect(screen.getAllByText("Running")).toHaveLength(1); // Ollama only
    expect(
      screen.getByText("Docker is installed but not running. Start Docker Desktop, then retry.")
    ).toBeInTheDocument();
  });

  it("a failing listHiveSessions call falls back to an empty list, not an error crash", async () => {
    listHiveSessionsMock.mockRejectedValue(new Error("list_hive_sessions failed"));
    render(<ExecutionWorkspace />);
    await waitFor(() => {
      expect(screen.getByText("No hive sessions currently running.")).toBeInTheDocument();
    });
  });
});
