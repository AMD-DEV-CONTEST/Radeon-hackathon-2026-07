import { render, screen, waitFor, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsProvider, useSettings } from "../SettingsContext";

const { invokeSafeMock, rawInvokeMock, isTauriMock } = vi.hoisted(() => ({
  invokeSafeMock: vi.fn(),
  rawInvokeMock: vi.fn(),
  isTauriMock: vi.fn(() => true),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => rawInvokeMock(...args),
}));

vi.mock("@/lib/api", () => ({
  getApiKeyStatus: vi.fn().mockResolvedValue({}),
  getToolRegistry: vi.fn().mockResolvedValue({ tools: [], coverage: "0/0" }),
  checkOllamaStatus: vi.fn().mockResolvedValue({ ok: false }),
  getModelsRegistry: vi.fn().mockResolvedValue({ tiers: [] }),
  getOllamaBaseUrl: vi.fn().mockResolvedValue(null),
  saveOllamaBaseUrl: vi.fn().mockResolvedValue(undefined),
  invokeSafe: invokeSafeMock,
  isTauri: () => isTauriMock(),
}));

function Probe() {
  const { networkPolicy, setNetworkPolicy, networkPolicyError } = useSettings();
  return (
    <div>
      <span data-testid="policy">{networkPolicy}</span>
      <span data-testid="error">{networkPolicyError ?? ""}</span>
      <button onClick={() => setNetworkPolicy("offline")}>go offline</button>
    </div>
  );
}

/**
 * Privacy posture is the one setting that must never be reported
 * optimistically. This previously went through invokeSafe in a
 * fire-and-forget `.catch(console.error)`, so a backend that never applied the
 * policy still left the UI (and localStorage) claiming "offline" -- the user
 * believed egress was blocked when it was not.
 */
describe("SettingsProvider network policy", () => {
  beforeEach(() => {
    invokeSafeMock.mockReset();
    invokeSafeMock.mockResolvedValue(null);
    rawInvokeMock.mockReset();
    rawInvokeMock.mockResolvedValue(null);
    isTauriMock.mockReturnValue(true);
    localStorage.clear();
  });

  it("pushes the stored policy to the backend on mount", async () => {
    render(
      <SettingsProvider>
        <div>child</div>
      </SettingsProvider>
    );

    await waitFor(() => {
      expect(rawInvokeMock).toHaveBeenCalledWith("sync_network_policy", { policy: "cloaked" });
    });
  });

  it("rolls the displayed policy back when the backend refuses it", async () => {
    render(
      <SettingsProvider>
        <Probe />
      </SettingsProvider>
    );
    await waitFor(() => expect(rawInvokeMock).toHaveBeenCalled());

    rawInvokeMock.mockRejectedValueOnce(new Error("policy daemon unavailable"));
    await act(async () => {
      screen.getByText("go offline").click();
    });

    await waitFor(() => expect(screen.getByTestId("error").textContent).toBeTruthy());
    // The critical assertion: the UI must NOT still claim "offline".
    expect(screen.getByTestId("policy").textContent).toBe("cloaked");
    expect(screen.getByTestId("error").textContent).toMatch(/policy daemon unavailable/i);
    expect(localStorage.getItem("determinex.networkPolicy")).not.toBe("offline");
  });

  it("keeps the new policy when the backend accepts it", async () => {
    render(
      <SettingsProvider>
        <Probe />
      </SettingsProvider>
    );
    await waitFor(() => expect(rawInvokeMock).toHaveBeenCalled());

    await act(async () => {
      screen.getByText("go offline").click();
    });

    await waitFor(() => expect(screen.getByTestId("policy").textContent).toBe("offline"));
    expect(screen.getByTestId("error").textContent).toBe("");
  });

  it("does not call the desktop backend in browser mode", async () => {
    isTauriMock.mockReturnValue(false);
    render(
      <SettingsProvider>
        <Probe />
      </SettingsProvider>
    );
    await act(async () => {
      screen.getByText("go offline").click();
    });
    // Browser mode has no Tauri IPC; calling invoke() there would reject and
    // produce a bogus "policy refused" warning.
    expect(rawInvokeMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("error").textContent).toBe("");
  });
});
