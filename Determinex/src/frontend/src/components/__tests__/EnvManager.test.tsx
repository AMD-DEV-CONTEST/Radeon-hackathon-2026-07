import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const invokeMock = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (...a: unknown[]) => invokeMock(...a) }));
vi.mock("@/lib/api", () => ({ isTauri: () => true }));

import { EnvManager } from "../buildtools/EnvManager";

const ROWS = [
  { key: "GITHUB_TOKEN", preview: "ghp_••••••••", length: 40, looksSecret: true },
  { key: "PORT", preview: "••••", length: 4, looksSecret: false },
];

describe("EnvManager", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    invokeMock.mockImplementation(async (cmd: string) =>
      cmd === "list_env_vars" ? ROWS : "ghp_therealsecretvalue"
    );
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it("lists real .env keys with masked values", async () => {
    render(<EnvManager workspacePath={"C:\\ws"} />);
    await waitFor(() => expect(screen.getByText("GITHUB_TOKEN")).toBeInTheDocument());
    // The masked preview is what renders -- never the value.
    expect(screen.getByText("ghp_••••••••")).toBeInTheDocument();
    expect(screen.queryByText(/therealsecretvalue/)).not.toBeInTheDocument();
  });

  it("does not fetch any value until the user reveals one", async () => {
    render(<EnvManager workspacePath={"C:\\ws"} />);
    await waitFor(() => expect(screen.getByText("GITHUB_TOKEN")).toBeInTheDocument());
    // Listing must not be a bulk secret dump.
    expect(invokeMock.mock.calls.some((c) => c[0] === "reveal_env_var")).toBe(false);
  });

  it("reveals exactly one key, on click", async () => {
    render(<EnvManager workspacePath={"C:\\ws"} />);
    await waitFor(() => expect(screen.getByText("GITHUB_TOKEN")).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText("Reveal GITHUB_TOKEN"));
    await waitFor(() => expect(screen.getByText("ghp_therealsecretvalue")).toBeInTheDocument());

    const reveals = invokeMock.mock.calls.filter((c) => c[0] === "reveal_env_var");
    expect(reveals).toHaveLength(1);
    expect(reveals[0][1]).toMatchObject({ key: "GITHUB_TOKEN", workspace: "C:\\ws" });
  });

  it("hides a revealed value again", async () => {
    render(<EnvManager workspacePath={"C:\\ws"} />);
    await waitFor(() => expect(screen.getByText("GITHUB_TOKEN")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Reveal GITHUB_TOKEN"));
    await waitFor(() => expect(screen.getByText("ghp_therealsecretvalue")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Hide GITHUB_TOKEN"));
    await waitFor(() =>
      expect(screen.queryByText("ghp_therealsecretvalue")).not.toBeInTheDocument()
    );
  });

  it("drops revealed values on reload rather than keeping them on screen", async () => {
    render(<EnvManager workspacePath={"C:\\ws"} />);
    await waitFor(() => expect(screen.getByText("GITHUB_TOKEN")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Reveal GITHUB_TOKEN"));
    await waitFor(() => expect(screen.getByText("ghp_therealsecretvalue")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("env-reload"));
    await waitFor(() =>
      expect(screen.queryByText("ghp_therealsecretvalue")).not.toBeInTheDocument()
    );
  });

  it("surfaces a backend refusal instead of showing an empty list", async () => {
    invokeMock.mockRejectedValue(new Error("Access denied: .env is outside the open workspace."));
    render(<EnvManager workspacePath={"C:\\ws"} />);
    await waitFor(() => expect(screen.getByText(/Access denied/)).toBeInTheDocument());
  });

  it("says nothing is there only after actually looking", async () => {
    invokeMock.mockImplementation(async () => []);
    render(<EnvManager workspacePath={"C:\\ws"} />);
    await waitFor(() => expect(screen.getByText(/No \.env in this workspace/)).toBeInTheDocument());
  });
});
