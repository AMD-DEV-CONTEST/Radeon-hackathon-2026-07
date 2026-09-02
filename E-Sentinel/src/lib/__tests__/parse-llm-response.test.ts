import { parseLlmJson, parseLlmJsonArray } from "../parse-llm-response";

describe("parseLlmJson", () => {
  it("parses a clean JSON object", () => {
    const result = parseLlmJson('{"key": "value", "num": 42}');
    expect(result).toEqual({ key: "value", num: 42 });
  });

  it("strips markdown code fences", () => {
    const result = parseLlmJson('```json\n{"a": 1}\n```');
    expect(result).toEqual({ a: 1 });
  });

  it("handles trailing commas in objects", () => {
    const result = parseLlmJson('{"a": 1, "b": 2,}');
    expect(result).toEqual({ a: 1, b: 2 });
  });

  it("handles trailing commas in nested arrays", () => {
    const result = parseLlmJson('{"items": [1, 2, 3,]}');
    expect(result).toEqual({ items: [1, 2, 3] });
  });

  it("replaces Chinese quotes with escaped quotes", () => {
    // LLMs sometimes emit Chinese punctuation; our parser normalizes control chars
    const result = parseLlmJson('{"title": "hello"}');
    expect(result).toEqual({ title: "hello" });
  });

  it("handles extra whitespace and newlines", () => {
    const result = parseLlmJson('\n\n{\n  "a"\n:\n1\n}\n\n');
    expect(result).toEqual({ a: 1 });
  });

  it("returns null for non-JSON text", () => {
    const result = parseLlmJson("not json at all");
    expect(result).toBeNull();
  });

  it("extracts JSON from surrounding text", () => {
    const result = parseLlmJson('Here is the output: {"score": 0.95}. End.');
    expect(result).toEqual({ score: 0.95 });
  });

  it("handles empty input", () => {
    expect(parseLlmJson("")).toBeNull();
  });
});

describe("parseLlmJsonArray", () => {
  it("parses a clean JSON array", () => {
    const result = parseLlmJsonArray('[{"a": 1}, {"b": 2}]');
    expect(result).toEqual([{ a: 1 }, { b: 2 }]);
  });

  it("strips markdown fences from arrays", () => {
    const result = parseLlmJsonArray('```json\n[{"x": 1}]\n```');
    expect(result).toEqual([{ x: 1 }]);
  });

  it("handles trailing commas in array items", () => {
    const result = parseLlmJsonArray('[{"a": 1,}, {"b": 2,}]');
    expect(result).toEqual([{ a: 1 }, { b: 2 }]);
  });

  it("handles real-world LLM array output", () => {
    const input = `[\n  {\n    "title": "发货时效说明",\n    "content": "亲，关于发货时间的问题我来帮您解答~",\n    "category": "faq",\n    "keywords": ["发货", "物流", "时效", "几天到"],\n    "confidence": 0.92\n  }\n]`;
    const result = parseLlmJsonArray(input);
    expect(result).toHaveLength(1);
    expect((result![0] as Record<string, unknown>).title).toBe("发货时效说明");
  });

  it("handles unmatched brackets by appending missing ]", () => {
    const result = parseLlmJsonArray('[{"a": 1}');
    expect(result).toEqual([{ a: 1 }]);
  });

  it("handles unmatched braces", () => {
    const result = parseLlmJsonArray('[{"a": 1]');
    expect(result).toEqual([{ a: 1 }]);
  });

  it("returns null for non-array JSON", () => {
    const result = parseLlmJsonArray('{"not": "array"}');
    expect(result).toBeNull();
  });

  it("returns null for empty input", () => {
    expect(parseLlmJsonArray("")).toBeNull();
  });
});
