import { describe, expect, it, vi } from "vitest";

import {
  requestSetupRerun,
  SETUP_COMPLETED_STORAGE_KEY,
  SETUP_RERUN_EVENT,
} from "../networkPolicy";

describe("setup rerun state", () => {
  it("clears setup completion and emits a rerun event", () => {
    window.localStorage.setItem(SETUP_COMPLETED_STORAGE_KEY, "true");
    const listener = vi.fn();
    window.addEventListener(SETUP_RERUN_EVENT, listener);

    requestSetupRerun();

    expect(window.localStorage.getItem(SETUP_COMPLETED_STORAGE_KEY)).toBeNull();
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(SETUP_RERUN_EVENT, listener);
  });
});
