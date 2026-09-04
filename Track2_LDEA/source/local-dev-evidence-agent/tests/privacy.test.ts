import { describe, expect, it } from "vitest";
import { redactText, scanMany, scanText } from "../src/privacy.js";

describe("privacy scan", () => {
  it("detects email and api key", () => {
    const risks = scanText("mail me at alice@corp.com key=sk-abcdefghijklmnopqrstuvwxyz0123456789");
    const kinds = risks.map((r) => r.kind);
    expect(kinds).toContain("email");
    expect(kinds).toContain("api_key");
  });

  it("redacts secrets", () => {
    const out = redactText("Bearer abcdefghijklmnop AND sk-abcdefghijklmnopqrstuvwxyz0123456789");
    expect(out).toContain("Bearer ***");
    expect(out).not.toContain("sk-abcdefghijklmnopqrstuvwxyz0123456789");
  });

  it("merges risks across files", () => {
    const risks = scanMany([
      { path: "a.txt", content: "demo@example.com" },
      { path: "b.env", content: "OPENAI_API_KEY=1\ndemo2@example.com" },
    ]);
    const email = risks.find((r) => r.kind === "email");
    expect(email?.count).toBe(2);
    expect(email?.paths).toEqual(expect.arrayContaining(["a.txt", "b.env"]));
  });
});
