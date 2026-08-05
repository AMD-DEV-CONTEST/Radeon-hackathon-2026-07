"use client";

/**
 * Named, restorable panel layouts.
 *
 * Ryan: "all of these boxes are locked, they should be able to be moved or
 * changed or deleted or setup however the user wants. this is too locked in."
 *
 * Individual widths were already persisted per surface, which handles "I always
 * want Source Control wide". It does not handle "I have a reviewing arrangement
 * and a building arrangement and I want to switch between them" -- the thing every
 * comparable tool (VS Code, Zed, Linear) provides. I originally wrote this up as a
 * feature request rather than building it, which was papering over the gap.
 *
 * A layout is deliberately a snapshot of the KEYS the rest of the app already
 * owns, not a second source of truth. Saving reads the same localStorage entries
 * `usePanelWidth` / `usePanelSplit` / the density setting write; restoring writes
 * them back and fires one event. Nothing here re-implements panel state, so a new
 * persisted panel dimension is captured automatically by prefix.
 */

export const LAYOUTS_STORAGE_KEY = "determinex.panelLayouts";
export const LAYOUT_RESTORED_EVENT = "determinex:layout-restored";

/** Prefixes whose localStorage entries constitute "the arrangement". */
const CAPTURED_PREFIXES = [
  "determinex.panelWidth.",
  "determinex.splitRatio.",
  "addonWindowLayouts",
  "determinex.uiDensity",
  "determinex.uiZoom",
];

export interface PanelLayout {
  name: string;
  savedAt: string;
  entries: Record<string, string>;
}

function isCaptured(key: string): boolean {
  return CAPTURED_PREFIXES.some((p) => key === p || key.startsWith(p));
}

export function readLayouts(storage?: Storage): PanelLayout[] {
  const s = storage ?? (typeof window === "undefined" ? undefined : window.localStorage);
  if (!s) return [];
  try {
    const parsed = JSON.parse(s.getItem(LAYOUTS_STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? (parsed as PanelLayout[]) : [];
  } catch {
    // A corrupt entry must not make the layout menu unusable.
    return [];
  }
}

function writeLayouts(layouts: PanelLayout[], storage?: Storage): void {
  const s = storage ?? (typeof window === "undefined" ? undefined : window.localStorage);
  if (!s) return;
  try {
    s.setItem(LAYOUTS_STORAGE_KEY, JSON.stringify(layouts));
  } catch {
    /* storage disabled */
  }
}

/** Snapshot the current arrangement under a name. Re-saving a name replaces it. */
export function captureLayout(name: string, storage?: Storage, now?: string): PanelLayout[] {
  const s = storage ?? (typeof window === "undefined" ? undefined : window.localStorage);
  if (!s) return [];
  const trimmed = name.trim();
  if (!trimmed) return readLayouts(s);

  const entries: Record<string, string> = {};
  for (let i = 0; i < s.length; i++) {
    const key = s.key(i);
    if (!key || !isCaptured(key)) continue;
    const value = s.getItem(key);
    if (value !== null) entries[key] = value;
  }

  const layout: PanelLayout = {
    name: trimmed,
    // Passed in rather than read from the clock so this is testable.
    savedAt: now ?? new Date().toISOString(),
    entries,
  };
  const rest = readLayouts(s).filter((l) => l.name !== trimmed);
  const next = [layout, ...rest];
  writeLayouts(next, s);
  return next;
}

/**
 * Restore a layout. Captured keys not present in the layout are REMOVED, so
 * restoring is exact rather than a merge with whatever is currently set --
 * otherwise a panel widened since the save would silently persist into it.
 */
export function restoreLayout(name: string, storage?: Storage): boolean {
  const s = storage ?? (typeof window === "undefined" ? undefined : window.localStorage);
  if (!s) return false;
  const layout = readLayouts(s).find((l) => l.name === name);
  if (!layout) return false;

  const stale: string[] = [];
  for (let i = 0; i < s.length; i++) {
    const key = s.key(i);
    if (key && isCaptured(key) && !(key in layout.entries)) stale.push(key);
  }
  stale.forEach((k) => s.removeItem(k));
  Object.entries(layout.entries).forEach(([k, v]) => s.setItem(k, v));

  if (typeof window !== "undefined") {
    // The hooks read localStorage on mount, so a live restore needs a signal.
    window.dispatchEvent(new Event(LAYOUT_RESTORED_EVENT));
  }
  return true;
}

export function deleteLayout(name: string, storage?: Storage): PanelLayout[] {
  const s = storage ?? (typeof window === "undefined" ? undefined : window.localStorage);
  if (!s) return [];
  const next = readLayouts(s).filter((l) => l.name !== name);
  writeLayouts(next, s);
  return next;
}

/** Clear every captured key, returning the app to its built-in defaults. */
export function resetLayout(storage?: Storage): void {
  const s = storage ?? (typeof window === "undefined" ? undefined : window.localStorage);
  if (!s) return;
  const keys: string[] = [];
  for (let i = 0; i < s.length; i++) {
    const key = s.key(i);
    if (key && isCaptured(key)) keys.push(key);
  }
  keys.forEach((k) => s.removeItem(k));
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(LAYOUT_RESTORED_EVENT));
  }
}
