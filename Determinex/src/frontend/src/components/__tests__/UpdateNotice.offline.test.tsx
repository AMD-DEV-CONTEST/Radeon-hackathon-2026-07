/**
 * The update check must not reach the network when the user has selected the offline policy.
 *
 * WHY THIS EXISTS
 * ---------------
 * `UpdateNotice` scheduled its check unconditionally, so an install set to `offline` still made an
 * outbound HTTPS request to github.com about 6s after every launch. This app ships an explicit
 * three-state network policy, and `AiRouterContext` already refuses to route a cloud model under
 * `offline` -- so the updater was quietly breaking a guarantee the rest of the product keeps, in a
 * product whose entire position is local-first.
 *
 * "It is only a version string" misses what was promised: the user asked for no network, and
 * something went to the network anyway. That is the same class of defect as a check that reports a
 * pass it never performed -- a stated property that isn't true.
 *
 * `cloaked` must still check. Cloaked allows cloud calls with identifiers obfuscated, and an update
 * check carries no repository identifiers at all, so suppressing it there would cost those users
 * their security fixes for no privacy gain. A test that only asserted "offline blocks" would pass
 * on a component that never checked at all, so both directions are pinned.
 */

import { render } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

const checkMock = vi.fn();
vi.mock("@tauri-apps/plugin-updater", () => ({ check: () => checkMock() }));

let policy = "offline";
vi.mock("@/contexts/SettingsContext", () => ({
  useSettings: () => ({ networkPolicy: policy }),
}));

import { UpdateNotice } from "../UpdateNotice";

describe("UpdateNotice network policy", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    checkMock.mockReset();
    checkMock.mockResolvedValue(null);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("never calls the updater under the offline policy", async () => {
    policy = "offline";
    render(<UpdateNotice />);
    // Well past the 6s scheduling delay.
    await vi.advanceTimersByTimeAsync(30_000);
    expect(checkMock).not.toHaveBeenCalled();
  });

  it("still checks under the cloaked policy", async () => {
    policy = "cloaked";
    render(<UpdateNotice />);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(checkMock).toHaveBeenCalled();
  });

  it("still checks under the online policy", async () => {
    policy = "online";
    render(<UpdateNotice />);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(checkMock).toHaveBeenCalled();
  });

  it("renders nothing at all when offline", async () => {
    policy = "offline";
    const { container } = render(<UpdateNotice />);
    await vi.advanceTimersByTimeAsync(30_000);
    // No notice means no Install button, so the manual download path is unreachable too -- which
    // matters if the policy is switched to offline while a notice is already displayed.
    expect(container).toBeEmptyDOMElement();
  });
});
