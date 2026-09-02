import { formatPercent, cn } from "../utils";

describe("formatPercent", () => {
  it("formats a 0-1 ratio as percentage string", () => {
    expect(formatPercent(0.855)).toBe("85.5%");
  });

  it("formats a numeric string as 0-1 ratio", () => {
    expect(formatPercent("0.923")).toBe("92.3%");
  });

  it("rounds to 1 decimal place", () => {
    expect(formatPercent(0.7666)).toBe("76.7%");
  });

  it("returns '—' for null", () => {
    expect(formatPercent(null)).toBe("—");
  });

  it("returns '—' for undefined", () => {
    expect(formatPercent(undefined)).toBe("—");
  });

  it("returns '—' for NaN string", () => {
    expect(formatPercent("not-a-number")).toBe("—");
  });

  it("handles zero", () => {
    expect(formatPercent(0)).toBe("0.0%");
  });

  it("returns '—' for values outside 0-1 range", () => {
    expect(formatPercent(-0.052)).toBe("—");
    expect(formatPercent(1.5)).toBe("—");
  });

  it("formats 100% as 100.0%", () => {
    expect(formatPercent(1)).toBe("100.0%");
  });
});

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("text-sm", "font-bold")).toBe("text-sm font-bold");
  });

  it("handles conditional classes", () => {
    expect(cn("base", false && "hidden", "extra")).toBe("base extra");
  });

  it("handles tailwind conflicts", () => {
    const result = cn("px-2 py-1", "px-4");
    expect(result).toContain("px-4");
    expect(result).not.toContain("px-2");
  });
});
