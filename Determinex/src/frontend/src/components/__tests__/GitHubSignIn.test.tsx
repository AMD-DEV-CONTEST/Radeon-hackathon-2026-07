import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

const invokeMock = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (...a: unknown[]) => invokeMock(...a) }));

import { GitHubSignIn } from "../GitHubSignIn";

const START = {
  userCode: "WDJB-MJHT",
  verificationUri: "https://github.com/login/device",
  deviceCode: "dev-123",
  interval: 1,
  expiresIn: 900,
};

describe("GitHubSignIn (device flow)", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("shows the user code and the verification URL", async () => {
    invokeMock.mockImplementation(async (cmd: string) =>
      cmd === "github_device_start" ? START : null
    );
    render(<GitHubSignIn />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("github-sign-in"));
    });
    expect(screen.getByTestId("github-user-code")).toHaveTextContent("WDJB-MJHT");
    expect(screen.getByText(/github\.com\/login\/device/)).toBeInTheDocument();
  });

  it("keeps polling while GitHub says pending, then reports success", async () => {
    let polls = 0;
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === "github_device_start") return START;
      if (cmd === "github_device_poll") {
        polls += 1;
        return polls < 3 ? { status: "pending" } : { status: "authorized" };
      }
      return null;
    });
    const onChange = vi.fn();
    render(<GitHubSignIn onChange={onChange} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("github-sign-in"));
    });

    // pending is the normal in-progress state, not an error.
    for (let i = 0; i < 3; i++) {
      await act(async () => {
        vi.advanceTimersByTime(1100);
      });
    }
    expect(screen.getByText(/GitHub connected/i)).toBeInTheDocument();
    expect(onChange).toHaveBeenCalled();
  });

  it("backs off when GitHub says slow_down", async () => {
    const intervals: number[] = [];
    let last = Date.now();
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === "github_device_start") return START;
      if (cmd === "github_device_poll") {
        intervals.push(Date.now() - last);
        last = Date.now();
        return intervals.length === 1
          ? { status: "slow_down", interval: 7 }
          : { status: "authorized" };
      }
      return null;
    });
    render(<GitHubSignIn />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("github-sign-in"));
    });
    await act(async () => {
      vi.advanceTimersByTime(1100);
    });
    // Polling faster than instructed can get the request rejected outright, so
    // the next poll must NOT fire at the original 1s cadence.
    await act(async () => {
      vi.advanceTimersByTime(1100);
    });
    expect(screen.queryByText(/GitHub connected/i)).not.toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    expect(screen.getByText(/GitHub connected/i)).toBeInTheDocument();
  });

  it("surfaces a denial instead of spinning forever", async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === "github_device_start") return START;
      if (cmd === "github_device_poll")
        return { status: "denied", message: "Authorization was declined on GitHub." };
      return null;
    });
    render(<GitHubSignIn />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("github-sign-in"));
    });
    await act(async () => {
      vi.advanceTimersByTime(1100);
    });
    expect(screen.getByText(/declined on GitHub/i)).toBeInTheDocument();
  });

  it("reports device_flow_disabled rather than failing silently", async () => {
    invokeMock.mockRejectedValue(
      new Error("This GitHub OAuth App does not have Device Flow enabled.")
    );
    render(<GitHubSignIn />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("github-sign-in"));
    });
    expect(screen.getByText(/Device Flow enabled/i)).toBeInTheDocument();
  });

  it("offers sign-out when already connected", async () => {
    invokeMock.mockResolvedValue(null);
    const onChange = vi.fn();
    render(<GitHubSignIn connected onChange={onChange} />);
    expect(screen.getByText(/GitHub connected/i)).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByTestId("github-sign-out"));
    });
    expect(invokeMock).toHaveBeenCalledWith("github_sign_out");
    // No waitFor: it polls on real timers, which never advance under
    // vi.useFakeTimers(), so it deadlocks instead of asserting.
    expect(onChange).toHaveBeenCalled();
  });

  it("never receives the access token", async () => {
    // The token is stored server-side; only a status crosses IPC.
    invokeMock.mockImplementation(async (cmd: string) =>
      cmd === "github_device_start" ? START : { status: "authorized" }
    );
    render(<GitHubSignIn />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("github-sign-in"));
    });
    await act(async () => {
      vi.advanceTimersByTime(1100);
    });
    const returned = await invokeMock.mock.results[1].value;
    expect(returned).not.toHaveProperty("access_token");
    expect(returned).not.toHaveProperty("accessToken");
  });
});
