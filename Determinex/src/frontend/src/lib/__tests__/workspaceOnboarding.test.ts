import { describe, expect, it } from "vitest";
import {
  hasDismissedOnboarding,
  markOnboardingDismissed,
  onboardingDismissKey,
  resolveWorkspaceRoot,
} from "../workspaceOnboarding";

/**
 * The bug this pins is a key mismatch, so the test that matters is the
 * round-trip: whatever Dismiss writes, the show-check must read.
 *
 * Previously the check used localStorage's "explorerRoot" (null on a fresh
 * install) and the write used React state seeded with a hard-coded
 * "C:\\Dev\\Determinex". Every new user dismissed the modal into a key nothing
 * read, so it reappeared on every launch with no escape.
 */

function fakeStorage() {
  const map = new Map<string, string>();
  return {
    map,
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
  };
}

describe("workspace onboarding dismissal", () => {
  it("round-trips on a fresh install, where nothing is persisted yet", () => {
    const store = fakeStorage();
    const DEFAULT_ROOT = "C:\\Dev\\Determinex";

    // What the mount effect sees: no saved root, state seeded with the default.
    const root = resolveWorkspaceRoot(null, DEFAULT_ROOT);
    expect(hasDismissedOnboarding(root, store)).toBe(false);

    // What Dismiss does: writes using the live explorerRoot, which by then is
    // that same default.
    markOnboardingDismissed(DEFAULT_ROOT, store);

    // The exact assertion that used to fail: the next launch must stay quiet.
    expect(hasDismissedOnboarding(resolveWorkspaceRoot(null, DEFAULT_ROOT), store)).toBe(true);
  });

  it("round-trips when a root has been persisted", () => {
    const store = fakeStorage();
    const saved = "D:\\work\\thing";
    const root = resolveWorkspaceRoot(saved, "C:\\Dev\\Determinex");
    expect(root).toBe(saved);

    markOnboardingDismissed(root, store);
    expect(hasDismissedOnboarding(resolveWorkspaceRoot(saved, "C:\\Dev\\Determinex"), store)).toBe(
      true
    );
  });

  it("still introduces itself for a different workspace, which is the point of keying by root", () => {
    const store = fakeStorage();
    markOnboardingDismissed("C:\\one", store);
    expect(hasDismissedOnboarding("C:\\one", store)).toBe(true);
    expect(hasDismissedOnboarding("C:\\two", store)).toBe(false);
  });

  it("falls back to a single stable key for an empty root", () => {
    expect(onboardingDismissKey("")).toBe("workspaceOnboardingDismissed:default");
    expect(onboardingDismissKey(null)).toBe("workspaceOnboardingDismissed:default");
    expect(onboardingDismissKey(undefined)).toBe("workspaceOnboardingDismissed:default");
  });

  it("never asks to show during SSR, where there is no storage to consult", () => {
    // Returning false here would render a blocking modal into the server HTML.
    // `null`, not `undefined`: undefined re-applies the default parameter, which
    // under jsdom is a real localStorage -- so this branch would have looked
    // covered while testing nothing.
    expect(hasDismissedOnboarding("C:\\anything", null)).toBe(true);
  });
});
