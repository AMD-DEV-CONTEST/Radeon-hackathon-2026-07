import { diffJson, hasChanges } from "../json-diff";

describe("diffJson", () => {
  it("returns empty diff for identical objects", () => {
    const obj = { a: 1, b: "hello" };
    const result = diffJson(obj, { ...obj });
    expect(result.added).toEqual({});
    expect(result.removed).toEqual({});
    expect(result.changed).toEqual({});
  });

  it("detects added keys", () => {
    const result = diffJson({ a: 1 }, { a: 1, b: 2 });
    expect(result.added).toEqual({ b: 2 });
    expect(result.removed).toEqual({});
    expect(result.changed).toEqual({});
  });

  it("detects removed keys", () => {
    const result = diffJson({ a: 1, b: 2 }, { a: 1 });
    expect(result.removed).toEqual({ b: 2 });
    expect(result.added).toEqual({});
    expect(result.changed).toEqual({});
  });

  it("detects changed values", () => {
    const result = diffJson({ a: 1, b: "old" }, { a: 1, b: "new" });
    expect(result.changed).toEqual({ b: { old: "old", new: "new" } });
  });

  it("handles nested objects in value comparison", () => {
    const result = diffJson(
      { config: { greeting: "Hello", timeout: 30 } },
      { config: { greeting: "Hi", timeout: 30 } }
    );
    expect(result.changed).toHaveProperty("config");
  });

  it("returns empty for empty objects", () => {
    const result = diffJson({}, {});
    expect(hasChanges(result)).toBe(false);
  });

  it("detects multiple simultaneous changes", () => {
    const result = diffJson(
      { a: 1, b: 2, c: 3 },
      { a: 1, b: 22, d: 4 }
    );
    expect(result.removed).toEqual({ c: 3 });
    expect(result.added).toEqual({ d: 4 });
    expect(result.changed).toEqual({ b: { old: 2, new: 22 } });
  });
});

describe("hasChanges", () => {
  it("returns false for empty diff", () => {
    expect(hasChanges({ added: {}, removed: {}, changed: {} })).toBe(false);
  });

  it("returns true when there are additions", () => {
    expect(hasChanges({ added: { x: 1 }, removed: {}, changed: {} })).toBe(true);
  });

  it("returns true when there are removals", () => {
    expect(hasChanges({ added: {}, removed: { x: 1 }, changed: {} })).toBe(true);
  });

  it("returns true when there are changes", () => {
    expect(hasChanges({ added: {}, removed: {}, changed: { x: { old: 1, new: 2 } } })).toBe(true);
  });
});
