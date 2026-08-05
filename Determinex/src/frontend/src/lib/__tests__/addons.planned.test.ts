/**
 * The Marketplace must not offer to install a capability that does not exist.
 *
 * WHY THIS EXISTS
 * ---------------
 * `MarketplacePanel.toggle()` only writes an addon id into localStorage -- nothing is provisioned.
 * The card then rendered "Installed". So a user could click Install on `kotlin-oracle` and be told
 * the Kotlin toolchain was present, while `_ORACLE_IMAGES` in scripts/hive/compiler.py contains only
 * rust, go, python and typescript and `validate_project` FAILS CLOSED for everything else. They
 * would meet that refusal having just been told the oracle was installed.
 *
 * This is the same defect as the LLM cards that reported "Installed" with no API key configured
 * (Ryan, live: "supposedly installed? but not...") -- a status asserted rather than established.
 *
 * The fix is the `planned` flag, and these tests pin the two halves that make it real: the set of
 * planned addons matches the languages the oracle actually refuses, and a planned addon can never be
 * rendered as installed regardless of what localStorage says.
 */

import { describe, expect, it } from "vitest";

import { ADDONS } from "../addons";

/** Languages the sandboxed compiler oracle really runs (`_ORACLE_IMAGES`). */
const ORACLE_WIRED_IDS = new Set(["rust-oracle", "go-oracle", "python-oracle", "ts-oracle"]);

describe("marketplace planned addons", () => {
  it("marks every oracle the compiler oracle does not support as planned", () => {
    const unwired = ADDONS.filter((a) => a.category === "oracle" && !ORACLE_WIRED_IDS.has(a.id));
    expect(unwired.length).toBeGreaterThan(0); // guards against the list being emptied by accident
    for (const addon of unwired) {
      expect(
        addon.planned,
        `${addon.id} is not wired into _ORACLE_IMAGES but is not marked planned`
      ).toBe(true);
    }
  });

  it("never marks a wired oracle as planned", () => {
    // The opposite failure: flagging a working oracle as planned would disable a real capability.
    for (const addon of ADDONS.filter((a) => ORACLE_WIRED_IDS.has(a.id))) {
      expect(addon.planned, `${addon.id} is wired but marked planned`).not.toBe(true);
    }
  });

  it("never ships a planned addon pre-marked as installed or builtin", () => {
    // `defaultInstalledAddonIds()` seeds from static status, so a planned addon with
    // status:"installed" would be treated as present on first launch, before any click.
    for (const addon of ADDONS.filter((a) => a.planned)) {
      expect(["installed", "builtin"]).not.toContain(addon.status);
    }
  });

  it("describes planned oracles in the future tense, not as though they run", () => {
    // The descriptions used to read "gradle test. JVM oracle for Android + backend Kotlin targets."
    // -- present tense, indistinguishable from a working oracle.
    for (const addon of ADDONS.filter((a) => a.planned && a.category === "oracle")) {
      expect(
        /planned|not .*yet|fails closed/i.test(addon.description),
        `${addon.id} description does not disclose that it is unavailable: "${addon.description}"`
      ).toBe(true);
    }
  });
});
