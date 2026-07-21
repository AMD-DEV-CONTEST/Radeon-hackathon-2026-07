import { describe, it, expect } from "vitest";
import { TYPE_TAG_COLORS, HEADER_GRADIENT, trustColor } from "../src/styles/theme";

describe("theme", () => {
  it("maps all 5 article types to tailwind colors", () => {
    expect(TYPE_TAG_COLORS.finding).toBe("text-red-500");
    expect(TYPE_TAG_COLORS.insight).toBe("text-blue-500");
    expect(TYPE_TAG_COLORS.warning).toBe("text-yellow-500");
    expect(TYPE_TAG_COLORS.precedent).toBe("text-violet-500");
    expect(TYPE_TAG_COLORS.procedure).toBe("text-green-500");
  });
  it("uses indigo\u2192purple gradient on header", () => {
    expect(HEADER_GRADIENT).toBe("bg-gradient-to-r from-indigo-600 to-purple-600");
  });
  it("green/yellow/red gradient for trust", () => {
    expect(trustColor(85)).toBe("text-green-500");
    expect(trustColor(55)).toBe("text-yellow-500");
    expect(trustColor(25)).toBe("text-red-500");
  });
});
