import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { ProjectHub } from "../ProjectHub";

const cloneRepoMock = vi.fn(async (_remoteUrl: string, _destination: string) => undefined);

vi.mock("../../lib/gitService", () => ({
  cloneRepo: (remoteUrl: string, destination: string) => cloneRepoMock(remoteUrl, destination),
}));

describe("ProjectHub add-project flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("requires a destination before attempting a clone", async () => {
    render(<ProjectHub onSelectProject={() => {}} onNavigate={() => {}} />);
    fireEvent.click(screen.getByText("Git Clone"));
    fireEvent.change(screen.getByTestId("project-hub-add-remote-input"), {
      target: { value: "https://github.com/example/repo.git" },
    });
    fireEvent.click(screen.getByTestId("project-hub-add-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("project-hub-add-error")).toHaveTextContent(/destination/i);
    });
    expect(cloneRepoMock).not.toHaveBeenCalled();
  });

  it("clones the repo and adds a real (non-placeholder) project cover on success", async () => {
    render(<ProjectHub onSelectProject={() => {}} onNavigate={() => {}} />);
    fireEvent.click(screen.getByText("Git Clone"));
    fireEvent.change(screen.getByTestId("project-hub-add-remote-input"), {
      target: { value: "https://github.com/example/repo.git" },
    });
    fireEvent.change(screen.getByTestId("project-hub-add-destination-input"), {
      target: { value: "C:\\Dev\\example-repo" },
    });
    fireEvent.click(screen.getByTestId("project-hub-add-submit"));

    await waitFor(() => {
      expect(cloneRepoMock).toHaveBeenCalledWith(
        "https://github.com/example/repo.git",
        "C:\\Dev\\example-repo"
      );
    });

    await waitFor(() => {
      expect(screen.getByText("C:\\Dev\\example-repo")).toBeInTheDocument();
    });
    // Persisted, not just in-memory -- survives a reload.
    const stored = JSON.parse(window.localStorage.getItem("determinex.userAddedProjects") || "[]");
    expect(stored).toHaveLength(1);
    expect(stored[0].localPath).toBe("C:\\Dev\\example-repo");
  });

  it("shows the real backend error and does not add a project when the clone fails", async () => {
    cloneRepoMock.mockRejectedValueOnce(
      new Error("destination already exists, refusing to overwrite: C:\\Dev\\taken")
    );
    render(<ProjectHub onSelectProject={() => {}} onNavigate={() => {}} />);
    fireEvent.click(screen.getByText("Git Clone"));
    fireEvent.change(screen.getByTestId("project-hub-add-remote-input"), {
      target: { value: "https://github.com/example/repo.git" },
    });
    fireEvent.change(screen.getByTestId("project-hub-add-destination-input"), {
      target: { value: "C:\\Dev\\taken" },
    });
    fireEvent.click(screen.getByTestId("project-hub-add-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("project-hub-add-error")).toHaveTextContent(/already exists/i);
    });
    expect(window.localStorage.getItem("determinex.userAddedProjects")).toBeNull();
  });

  it("restores a persisted user-added project cover after remount", async () => {
    window.localStorage.setItem(
      "determinex.userAddedProjects",
      JSON.stringify([
        {
          id: "restored-project-1",
          name: "Restored Project",
          localPath: "C:\\Dev\\restored-project",
          remote: "https://github.com/example/restored.git",
          provider: "Git",
          branch: "main",
          status: "needs-proof",
          stack: ["Unscanned", "Read-only"],
          defaultView: "workspace",
          lastOpened: "Just added",
          lastRun: "Cloned, workspace scan pending",
          proof: "No verifier run",
        },
      ])
    );
    render(<ProjectHub onSelectProject={() => {}} onNavigate={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText("Restored Project")).toBeInTheDocument();
    });
  });
});
