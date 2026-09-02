import { describe, expect, it } from "vitest";

import { SKIN_PACKS, getCodeLayerStyle, getSkinPackStyle } from "@/theme/skinPacks";

/**
 * The code-surface layer must work for EVERY skin, not just the default.
 *
 * WHY THIS EXISTS
 * 28 components styled their chrome with literal GitHub hex -- 681 literal hex values in
 * total, #30363d alone appearing 168 times. A skin applies its palette as CSS variables
 * on the root element, so a literal hex ignores all 27 skins: half the app did not respond
 * to the theme picker at all. Those literals are now tokens derived from the active skin.
 *
 * Derivation is only an improvement if it holds across the whole skin set, including the
 * light one, so this iterates all of them rather than spot-checking Determinex.
 */

const CODE_TOKENS = [
  "--dtx-code-bg-deep",
  "--dtx-code-bg",
  "--dtx-code-panel",
  "--dtx-code-raised",
  "--dtx-code-border",
  "--dtx-code-border-subtle",
  "--dtx-code-text",
  "--dtx-code-muted",
] as const;

const SEMANTIC_TOKENS = ["--dtx-ok", "--dtx-warn", "--dtx-fail", "--dtx-info"] as const;

const packs = Object.values(SKIN_PACKS);

function luminance(color: string): number | null {
  const rgb = color.match(/^#([0-9a-f]{6})$/i);
  if (rgb) {
    const h = rgb[1];
    return (
      0.299 * parseInt(h.slice(0, 2), 16) +
      0.587 * parseInt(h.slice(2, 4), 16) +
      0.114 * parseInt(h.slice(4, 6), 16)
    );
  }
  const rgba = color.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i);
  if (rgba) {
    return 0.299 * parseFloat(rgba[1]) + 0.587 * parseFloat(rgba[2]) + 0.114 * parseFloat(rgba[3]);
  }
  return null;
}

describe("code layer derivation", () => {
  it("has skins to check at all", () => {
    // A zero-length pack list would make every test below pass vacuously.
    expect(packs.length).toBeGreaterThanOrEqual(20);
  });

  it.each(packs.map((p) => [p.id, p] as const))(
    "%s produces every token as a valid colour",
    (_id, pack) => {
      const style = getCodeLayerStyle(pack);
      for (const token of [...CODE_TOKENS, ...SEMANTIC_TOKENS]) {
        const value = style[token];
        expect(value, `${token} missing`).toBeTruthy();
        expect(value, `${token} = ${value}`).not.toMatch(/NaN|undefined|null/);
        expect(value, `${token} = ${value}`).toMatch(/^(#[0-9a-f]{6}|rgba?\()/i);
      }
    }
  );

  it.each(packs.map((p) => [p.id, p] as const))(
    "%s recedes in the right direction",
    (_id, pack) => {
      // On a dark skin a code surface must be no lighter than the shell background; on a
      // light skin (plainlight) it must be no darker. Getting this backwards inverts the
      // panels and destroys text contrast, which is the one failure mode that would make
      // the whole change worse than the literals it replaces.
      const style = getCodeLayerStyle(pack);
      const shell = luminance(pack.colors.bg);
      const code = luminance(style["--dtx-code-bg"]);
      if (shell === null || code === null) return;
      if (shell > 140) {
        expect(code, `light skin ${pack.id}: code bg went darker`).toBeGreaterThanOrEqual(
          shell - 1
        );
      } else {
        expect(code, `dark skin ${pack.id}: code bg went lighter`).toBeLessThanOrEqual(shell + 1);
      }
    }
  );

  it.each(packs.map((p) => [p.id, p] as const))(
    "%s drains chroma from code borders",
    (_id, pack) => {
      // The whole point of a separate code layer: a neon hairline on every row of a dense
      // table is noise. Before rgba() parsing was added, skins whose border is rgba()
      // silently kept their neon border -- the derivation no-opped and nothing noticed.
      const style = getCodeLayerStyle(pack);
      const derived = style["--dtx-code-border"];
      const channels = derived.match(/\d+/g)?.slice(0, 3).map(Number);
      const source = pack.colors.border.match(/[\d a-f]+/gi);
      if (!channels || channels.length < 3 || !source) return;
      const spread = Math.max(...channels) - Math.min(...channels);
      expect(spread, `${pack.id} border still highly saturated: ${derived}`).toBeLessThan(90);
    }
  );

  it("preserves translucency on a translucent source border", () => {
    // rgba in, rgba out. Losing the alpha turns a hairline into a solid rule.
    const determinex = SKIN_PACKS.determinex;
    expect(determinex.colors.border).toMatch(/^rgba\(/);
    expect(getCodeLayerStyle(determinex)["--dtx-code-border"]).toMatch(/^rgba\(/);
  });

  it("ships the code tokens through getSkinPackStyle, which is what the app applies", () => {
    // The derivation being correct is useless if it never reaches the DOM. page.tsx
    // spreads getSkinPackStyle() onto the root element.
    const style = getSkinPackStyle(SKIN_PACKS.determinex) as Record<string, string>;
    for (const token of CODE_TOKENS) {
      expect(style[token], `${token} not emitted`).toBeTruthy();
    }
    // A skin's own explicit values must still win over anything derived.
    expect(style["--determinex-bg"]).toBe(SKIN_PACKS.determinex.colors.bg);
  });

  it("keeps semantic colours constant across skins", () => {
    // "pass" has to stay recognisably green, or the meaning moves with the decoration.
    const oks = new Set(packs.map((p) => getCodeLayerStyle(p)["--dtx-ok"]));
    expect(oks.size).toBe(1);
  });
});
