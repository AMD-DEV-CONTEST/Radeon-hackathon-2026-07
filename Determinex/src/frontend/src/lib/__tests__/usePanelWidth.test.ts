import { renderHook, act } from "@testing-library/react";
import { describe, expect, it, beforeEach } from "vitest";
import { usePanelWidth, panelWidthStorageKey } from "../usePanelWidth";

function drag(startResize: (e: any) => void, from: number, to: number) {
  act(() => startResize({ clientX: from, preventDefault: () => {} }));
  act(() => {
    window.dispatchEvent(new PointerEvent("pointermove", { clientX: to }));
  });
  act(() => {
    window.dispatchEvent(new PointerEvent("pointerup", { clientX: to }));
  });
}

describe("usePanelWidth", () => {
  beforeEach(() => localStorage.clear());

  it("starts at the default when nothing is stored", () => {
    const { result } = renderHook(() => usePanelWidth("zone1.hive", 460));
    expect(result.current.width).toBe(460);
  });

  it("widens as the handle is dragged right", () => {
    const { result } = renderHook(() => usePanelWidth("zone1.hive", 460));
    drag(result.current.startResize, 500, 620);
    expect(result.current.width).toBe(580); // 460 + 120
  });

  it("persists per surface, so one panel's width does not move another's", () => {
    const a = renderHook(() => usePanelWidth("zone1.git", 760));
    drag(a.result.current.startResize, 100, 200);
    expect(localStorage.getItem(panelWidthStorageKey("zone1.git"))).toBe("860");
    // A different surface keeps its own default.
    const b = renderHook(() => usePanelWidth("zone1.proof", 380));
    expect(b.result.current.width).toBe(380);
  });

  it("restores a stored width on mount", () => {
    localStorage.setItem(panelWidthStorageKey("zone1.hive"), "612");
    const { result } = renderHook(() => usePanelWidth("zone1.hive", 460));
    expect(result.current.width).toBe(612);
  });

  it("clamps to min and max, including a corrupt stored value", () => {
    const { result } = renderHook(() => usePanelWidth("zone1.hive", 460, { min: 300, max: 800 }));
    drag(result.current.startResize, 500, 100); // would be 60
    expect(result.current.width).toBe(300);
    drag(result.current.startResize, 100, 2000);
    expect(result.current.width).toBe(800);

    localStorage.setItem(panelWidthStorageKey("zone1.wide"), "99999");
    const restored = renderHook(() => usePanelWidth("zone1.wide", 460, { min: 300, max: 800 }));
    expect(restored.result.current.width).toBe(800);
  });

  it("reports resizing state so the handle can show feedback", () => {
    const { result } = renderHook(() => usePanelWidth("zone1.hive", 460));
    expect(result.current.resizing).toBe(false);
    act(() => result.current.startResize({ clientX: 0, preventDefault: () => {} }));
    expect(result.current.resizing).toBe(true);
    act(() => {
      window.dispatchEvent(new PointerEvent("pointerup", { clientX: 0 }));
    });
    expect(result.current.resizing).toBe(false);
  });

  it("commits once on pointer-up, not on every move", () => {
    const { result } = renderHook(() => usePanelWidth("zone1.hive", 460));
    act(() => result.current.startResize({ clientX: 0, preventDefault: () => {} }));
    act(() => {
      window.dispatchEvent(new PointerEvent("pointermove", { clientX: 50 }));
    });
    // Mid-gesture: applied to the UI but not yet written.
    expect(result.current.width).toBe(510);
    expect(localStorage.getItem(panelWidthStorageKey("zone1.hive"))).toBeNull();
    act(() => {
      window.dispatchEvent(new PointerEvent("pointerup", { clientX: 50 }));
    });
    expect(localStorage.getItem(panelWidthStorageKey("zone1.hive"))).toBe("510");
  });
});
