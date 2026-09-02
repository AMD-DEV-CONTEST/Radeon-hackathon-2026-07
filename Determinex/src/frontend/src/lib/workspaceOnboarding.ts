"use client";

/**
 * One key derivation for the workspace-onboarding "don't show me again" flag.
 *
 * There were two, and they disagreed. The show-check read
 * `workspaceOnboardingDismissed:${savedRoot || "default"}` where `savedRoot` is
 * `localStorage.getItem("explorerRoot")`, while the Dismiss handler wrote
 * `workspaceOnboardingDismissed:${explorerRoot || "default"}` where
 * `explorerRoot` is React state whose initial value is a hard-coded
 * `"C:\\Dev\\Determinex"`.
 *
 * On any profile that has never persisted `explorerRoot` -- i.e. every new
 * install -- `savedRoot` is null and `explorerRoot` is not, so the check looked
 * at `:default` and the dismissal wrote `:C:\Dev\Determinex`. The flag was
 * always written to a key nothing ever read, and the full-screen onboarding
 * modal came back on every single launch with no way to stop it.
 *
 * Keying by workspace root is deliberate and kept: opening a different project
 * SHOULD introduce it again. Only the disagreement was the bug.
 */

export const ONBOARDING_DISMISS_PREFIX = "workspaceOnboardingDismissed:";

/** The single key both the read and the write must use. */
export function onboardingDismissKey(root: string | null | undefined): string {
  return `${ONBOARDING_DISMISS_PREFIX}${root || "default"}`;
}

/**
 * The root the app will actually be showing, given what was persisted and the
 * in-memory default.
 *
 * The mount effect reads `savedRoot` and calls `setExplorerRoot(savedRoot)`, so
 * by the time Dismiss runs, `explorerRoot` is the saved root when there was one
 * and the fallback when there wasn't. Resolving the same way here is what keeps
 * the two sides pointing at one key.
 */
export function resolveWorkspaceRoot(
  savedRoot: string | null | undefined,
  fallback: string
): string {
  return savedRoot || fallback;
}

/**
 * `storage` is explicit rather than reached for internally so the no-storage
 * branch is reachable from a test: passing `undefined` would just re-apply the
 * default, and under jsdom that default is a real localStorage -- so the SSR case
 * would have been untestable and silently uncovered. Pass `null` to mean "no
 * storage available".
 */
export function hasDismissedOnboarding(
  root: string | null | undefined,
  storage: Pick<Storage, "getItem"> | null | undefined = typeof window === "undefined"
    ? null
    : window.localStorage
): boolean {
  if (!storage) return true; // SSR: never render a blocking modal into server HTML
  return storage.getItem(onboardingDismissKey(root)) !== null;
}

export function markOnboardingDismissed(
  root: string | null | undefined,
  storage: Pick<Storage, "setItem"> | null | undefined = typeof window === "undefined"
    ? null
    : window.localStorage
): void {
  storage?.setItem(onboardingDismissKey(root), "1");
}
