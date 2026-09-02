import { describe, expect, it, beforeEach } from "vitest";

import {
  ADDON_STORAGE_KEY,
  LEGACY_ADDON_STORAGE_KEY,
  readInstalledAddonIds,
  writeInstalledAddonIds,
} from "../addonStorage";

describe("add-on storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("migrates legacy Determinex installed add-ons to the Determinex key", () => {
    window.localStorage.setItem(LEGACY_ADDON_STORAGE_KEY, JSON.stringify(["gemini", "mistral"]));

    const installed = readInstalledAddonIds(window.localStorage);

    expect(installed.has("gemini")).toBe(true);
    expect(installed.has("mistral")).toBe(true);
    expect(window.localStorage.getItem(ADDON_STORAGE_KEY)).toContain("gemini");
    expect(window.localStorage.getItem(ADDON_STORAGE_KEY)).toContain("mistral");
  });

  it("stores only user-installed add-ons under the Determinex key", () => {
    writeInstalledAddonIds(window.localStorage, new Set(["python-pytest", "gemini"]));

    expect(JSON.parse(window.localStorage.getItem(ADDON_STORAGE_KEY) || "[]")).toEqual(["gemini"]);
  });
});

describe("uninstall persistence", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("keeps a seeded add-on uninstalled across reads", () => {
    // THE REGRESSION. readInstalledAddonIds used to merge defaultInstalledAddonIds() -- every
    // addon whose STATIC status is "installed" -- back in on every read, while
    // writeInstalledAddonIds only excluded "builtin". So Uninstall wrote a list without the addon
    // and the next read restored it: reload, and it showed "Installed" again. Confirmed against
    // real seeded ids (swebench is status "installed" in ADDONS).
    const seeded = readInstalledAddonIds(window.localStorage);
    expect(seeded.has("swebench")).toBe(true);

    const remaining = new Set([...seeded].filter((id) => id !== "swebench"));
    writeInstalledAddonIds(window.localStorage, remaining);

    const afterReload = readInstalledAddonIds(window.localStorage);
    expect(afterReload.has("swebench")).toBe(false);
  });

  it("still forces builtins back in, because those are not removable", () => {
    readInstalledAddonIds(window.localStorage);
    writeInstalledAddonIds(window.localStorage, new Set());

    const afterReload = readInstalledAddonIds(window.localStorage);
    // rust-oracle is status "builtin"; it must survive an attempt to remove it.
    expect(afterReload.has("rust-oracle")).toBe(true);
  });
});
