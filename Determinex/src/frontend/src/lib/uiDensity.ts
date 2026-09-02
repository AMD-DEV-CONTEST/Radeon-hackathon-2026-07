"use client";

/**
 * UI density and zoom.
 *
 * Measured 2026-07-28: 84% of visible text rendered below 11px and the app's most
 * common font size was 9px. The type scale in globals.css fixes the default; this
 * makes it the user's choice rather than swapping one hard-coded decision for
 * another, which is what VS Code, Zed and Linear all do.
 *
 * One CSS variable does the work: every tier in the scale is
 * `calc(<px> * var(--dtx-font-scale))`, so density is a single attribute on
 * <html> and zoom is a single variable write. No re-layout, no second sweep.
 */

export type UiDensity = "compact" | "comfortable" | "spacious";

export const UI_DENSITY_STORAGE_KEY = "determinex.uiDensity";
export const UI_ZOOM_STORAGE_KEY = "determinex.uiZoom";

export const DENSITY_LABELS: Record<UiDensity, { label: string; hint: string }> = {
  compact: {
    label: "Compact",
    hint: "Closest to the previous sizing. More on screen, harder to read.",
  },
  comfortable: { label: "Comfortable", hint: "Default. 13px body, 11px floor." },
  spacious: { label: "Spacious", hint: "Larger type for high-resolution displays." },
};

const ZOOM_MIN = 0.8;
const ZOOM_MAX = 1.6;
const ZOOM_STEP = 0.1;

export function clampZoom(z: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(z * 100) / 100));
}

export function isUiDensity(v: unknown): v is UiDensity {
  return v === "compact" || v === "comfortable" || v === "spacious";
}

export function readStoredDensity(): UiDensity {
  if (typeof window === "undefined") return "comfortable";
  const raw = window.localStorage.getItem(UI_DENSITY_STORAGE_KEY);
  return isUiDensity(raw) ? raw : "comfortable";
}

export function readStoredZoom(): number {
  if (typeof window === "undefined") return 1;
  const raw = Number(window.localStorage.getItem(UI_ZOOM_STORAGE_KEY));
  return Number.isFinite(raw) && raw > 0 ? clampZoom(raw) : 1;
}

/**
 * Apply both to the document. Density picks the base multiplier via a
 * `data-density` attribute (globals.css owns the values); zoom multiplies on top,
 * so the two compose instead of fighting.
 */
export function applyDensity(density: UiDensity, zoom: number): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.setAttribute("data-density", density);
  const base = density === "compact" ? 0.88 : density === "spacious" ? 1.12 : 1;
  root.style.setProperty(
    "--dtx-font-scale",
    String(Math.round(base * clampZoom(zoom) * 1000) / 1000)
  );
}

export function nextZoom(current: number, direction: "in" | "out" | "reset"): number {
  if (direction === "reset") return 1;
  return clampZoom(current + (direction === "in" ? ZOOM_STEP : -ZOOM_STEP));
}
