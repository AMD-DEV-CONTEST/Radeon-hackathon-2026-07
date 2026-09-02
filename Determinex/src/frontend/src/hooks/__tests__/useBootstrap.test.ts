import { renderHook, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

const invokeSafeMock = vi.fn();

vi.mock("@/lib/api", () => ({
  isTauri: () => true,
  invokeSafe: (...args: unknown[]) => invokeSafeMock(...args),
}));

import { useBootstrap } from "../useBootstrap";

/**
 * The splash used to be inescapable. Its progress bar is a setTimeout
 * animation rather than real progress, and invokeSafe never throws -- it
 * returns null -- so the .catch() that was supposed to surface a boot failure
 * could never fire and nothing bounded the wait. A backend that never answered
 * left the app on the splash forever, still animating. Observed live stuck at
 * 65%.
 */
describe("useBootstrap never traps the user on the splash", () => {
  beforeEach(() => {
    invokeSafeMock.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("gives up with an error if initialize_system never resolves", async () => {
    // A promise that never settles == the hang this guards against.
    invokeSafeMock.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useBootstrap());

    expect(result.current.isBootstrapping).toBe(true);

    await act(async () => {
      vi.advanceTimersByTime(90_001);
    });

    expect(result.current.isBootstrapping).toBe(false);
    expect(result.current.bootError).toMatch(/did not finish within 90 seconds/i);
  });

  it("treats a null result as a failure, not a successful boot", async () => {
    // invokeSafe returns null when the command genuinely failed.
    invokeSafeMock.mockResolvedValue(null);
    const { result } = renderHook(() => useBootstrap());

    // Note: no waitFor here -- it polls on real timers, which never advance
    // under vi.useFakeTimers(), so it deadlocks instead of asserting.
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.bootError).toMatch(/initialize_system failed/i);
    expect(result.current.isBootstrapping).toBe(false);
  });

  it("completes normally on a real result and reports the tier", async () => {
    invokeSafeMock.mockResolvedValue({ tier: "engineer" });
    const { result } = renderHook(() => useBootstrap());

    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(400);
    });

    expect(result.current.bootTier).toBe("engineer");
    expect(result.current.bootError).toBeNull();
    expect(result.current.isBootstrapping).toBe(false);
  });

  it("does not fire the timeout after a successful boot", async () => {
    invokeSafeMock.mockResolvedValue({ tier: "engineer" });
    const { result } = renderHook(() => useBootstrap());

    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(120_000);
    });

    // The success path must win permanently; a late timeout must not overwrite
    // a good boot with a spurious error.
    expect(result.current.bootError).toBeNull();
    expect(result.current.bootTier).toBe("engineer");
  });
});
