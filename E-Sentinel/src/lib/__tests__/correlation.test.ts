import { createCorrelationId } from "../correlation";

describe("createCorrelationId", () => {
  it("returns a string with default prefix", () => {
    const id = createCorrelationId();
    expect(typeof id).toBe("string");
    expect(id.startsWith("qa_")).toBe(true);
  });

  it("returns a string with custom prefix", () => {
    const id = createCorrelationId("feishu");
    expect(id.startsWith("feishu_")).toBe(true);
  });

  it("generates unique IDs across multiple calls", () => {
    const ids = new Set(Array.from({ length: 20 }, () => createCorrelationId()));
    // With real nanoid, all 20 should be unique
    expect(ids.size).toBe(20);
  });

  it("has expected format (prefix_underscore_plus_alphanumeric)", () => {
    const id = createCorrelationId();
    expect(id).toMatch(/^qa_[A-Za-z0-9_-]+$/);
    // "qa_" (3) + 12 nanoid chars = 15
    expect(id.length).toBe(15);
  });
});
