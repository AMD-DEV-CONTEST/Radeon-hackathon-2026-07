import { describe, expect, it } from "vitest";
import {
  captureLayout,
  deleteLayout,
  readLayouts,
  resetLayout,
  restoreLayout,
} from "../panelLayouts";

/**
 * Named layouts exist because per-surface widths only answer "Source Control
 * should always be wide", not "I have a reviewing arrangement and a building
 * arrangement". Ryan asked for the second twice.
 *
 * The subtle requirement, and the one worth a test: restoring must be EXACT, not a
 * merge. If a panel was widened after the layout was saved, a merge would leave
 * that width in place and the restore would be quietly wrong -- which is the whole
 * value of the feature gone, in the least visible way possible.
 */

function fakeStorage(seed: Record<string, string> = {}): Storage {
  const map = new Map(Object.entries(seed));
  return {
    get length() {
      return map.size;
    },
    key: (i: number) => [...map.keys()][i] ?? null,
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
  } as Storage;
}

const ARRANGEMENT = {
  "determinex.panelWidth.zone1.hive": "460",
  "determinex.panelWidth.zone1.git": "760",
  "determinex.splitRatio.workCockpit": "0.55",
  "determinex.uiDensity": "comfortable",
  // Not part of an arrangement -- must never be captured or clobbered.
  "determinex.setupCompleted": "true",
  explorerRoot: "C:/work",
};

describe("named panel layouts", () => {
  it("captures only the arrangement keys, never unrelated state", () => {
    const s = fakeStorage(ARRANGEMENT);
    const [layout] = captureLayout("review", s, "2026-07-28T00:00:00Z");

    expect(Object.keys(layout.entries).sort()).toEqual([
      "determinex.panelWidth.zone1.git",
      "determinex.panelWidth.zone1.hive",
      "determinex.splitRatio.workCockpit",
      "determinex.uiDensity",
    ]);
    // Capturing setup state or the workspace root into a "layout" would mean
    // restoring one could log you back into onboarding or switch your project.
    expect(layout.entries["determinex.setupCompleted"]).toBeUndefined();
    expect(layout.entries["explorerRoot"]).toBeUndefined();
  });

  it("restores exactly, removing a width added after the save", () => {
    const s = fakeStorage(ARRANGEMENT);
    captureLayout("review", s, "2026-07-28T00:00:00Z");

    // The user then widens Proof and narrows Source Control.
    s.setItem("determinex.panelWidth.zone1.proof", "900");
    s.setItem("determinex.panelWidth.zone1.git", "300");

    expect(restoreLayout("review", s)).toBe(true);
    expect(s.getItem("determinex.panelWidth.zone1.git")).toBe("760");
    // THE assertion: a merge would leave Proof at 900 and the restore would be
    // silently partial.
    expect(s.getItem("determinex.panelWidth.zone1.proof")).toBeNull();
  });

  it("leaves non-arrangement state untouched when restoring", () => {
    const s = fakeStorage(ARRANGEMENT);
    captureLayout("review", s, "2026-07-28T00:00:00Z");
    restoreLayout("review", s);
    expect(s.getItem("determinex.setupCompleted")).toBe("true");
    expect(s.getItem("explorerRoot")).toBe("C:/work");
  });

  it("re-saving a name replaces it rather than duplicating", () => {
    const s = fakeStorage(ARRANGEMENT);
    captureLayout("review", s, "2026-07-28T00:00:00Z");
    s.setItem("determinex.panelWidth.zone1.hive", "999");
    const layouts = captureLayout("review", s, "2026-07-28T01:00:00Z");

    expect(layouts.filter((l) => l.name === "review")).toHaveLength(1);
    expect(layouts[0].entries["determinex.panelWidth.zone1.hive"]).toBe("999");
  });

  it("reports failure for an unknown layout instead of clearing everything", () => {
    const s = fakeStorage(ARRANGEMENT);
    expect(restoreLayout("does-not-exist", s)).toBe(false);
    // A restore that wiped the arrangement on a typo would be worse than no-op.
    expect(s.getItem("determinex.panelWidth.zone1.hive")).toBe("460");
  });

  it("deletes a layout without touching the live arrangement", () => {
    const s = fakeStorage(ARRANGEMENT);
    captureLayout("a", s, "2026-07-28T00:00:00Z");
    captureLayout("b", s, "2026-07-28T00:00:01Z");
    expect(deleteLayout("a", s).map((l) => l.name)).toEqual(["b"]);
    expect(s.getItem("determinex.panelWidth.zone1.hive")).toBe("460");
  });

  it("reset clears the arrangement and nothing else", () => {
    const s = fakeStorage(ARRANGEMENT);
    resetLayout(s);
    expect(s.getItem("determinex.panelWidth.zone1.hive")).toBeNull();
    expect(s.getItem("determinex.splitRatio.workCockpit")).toBeNull();
    expect(s.getItem("determinex.uiDensity")).toBeNull();
    expect(s.getItem("determinex.setupCompleted")).toBe("true");
    expect(s.getItem("explorerRoot")).toBe("C:/work");
  });

  it("survives a corrupt layouts entry rather than breaking the menu", () => {
    const s = fakeStorage({ ...ARRANGEMENT, "determinex.panelLayouts": "{not json" });
    expect(readLayouts(s)).toEqual([]);
    // And can still save over it.
    expect(captureLayout("fresh", s, "2026-07-28T00:00:00Z")).toHaveLength(1);
  });

  it("ignores a blank name", () => {
    const s = fakeStorage(ARRANGEMENT);
    expect(captureLayout("   ", s, "2026-07-28T00:00:00Z")).toEqual([]);
  });
});
