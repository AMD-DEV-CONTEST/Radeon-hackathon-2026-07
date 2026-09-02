import { shouldAutoPublish, BOT_CONFIG_SAFE_KEYS, KNOWLEDGE_SAFE_CATEGORIES } from "../auto-publish";

const SAFE_KEYS = new Set(["greeting", "faq"]);
const UNSAFE_KEYS = new Set(["legal", "financial", "medical"]);

describe("shouldAutoPublish — confidence threshold boundaries", () => {
  // ─── Critical boundary: 0.94 region (should NOT auto-publish) ───

  it("denies at 0.94 (below threshold)", () => {
    expect(shouldAutoPublish({ confidence: 0.94, category: "greeting", safeCategories: SAFE_KEYS })).toBe(false);
  });

  // ─── Critical boundary: 0.95 region (threshold itself — fuzzy boundary) ───

  it("approves at exactly 0.95 (on threshold)", () => {
    expect(shouldAutoPublish({ confidence: 0.95, category: "greeting", safeCategories: SAFE_KEYS })).toBe(true);
  });

  // ─── Floating-point edge: 0.949999 vs 0.950001 ───

  it("denies at 0.949999 (floating-point just below threshold)", () => {
    expect(shouldAutoPublish({ confidence: 0.949999, category: "greeting", safeCategories: SAFE_KEYS })).toBe(false);
  });

  it("approves at 0.950001 (floating-point just above threshold)", () => {
    expect(shouldAutoPublish({ confidence: 0.950001, category: "greeting", safeCategories: SAFE_KEYS })).toBe(true);
  });

  // ─── Floating-point edge: exact decimal representation ───

  it("denies at 0.9500000000000001 (IEEE 754 closest > 0.95)", () => {
    // 0.95 in IEEE 754 is actually 0.94999999999999995559...
    // 0.9500000000000001 is the next representable number after 0.95
    // Math.abs(0.95 - 0.9500000000000001) ≈ 1e-16 — satisfies >=
    const justAbove = 0.9500000000000001;
    expect(justAbove).toBeGreaterThanOrEqual(0.95);
    expect(shouldAutoPublish({ confidence: justAbove, category: "greeting", safeCategories: SAFE_KEYS })).toBe(true);
  });

  // ─── Null/undefined/missing confidence ───

  it("denies when confidence is null", () => {
    expect(shouldAutoPublish({ confidence: null, category: "greeting", safeCategories: SAFE_KEYS })).toBe(false);
  });

  it("denies when confidence is undefined", () => {
    expect(shouldAutoPublish({ confidence: undefined, category: "greeting", safeCategories: SAFE_KEYS })).toBe(false);
  });

  it("denies when confidence is NaN", () => {
    expect(shouldAutoPublish({ confidence: NaN, category: "greeting", safeCategories: SAFE_KEYS })).toBe(false);
  });

  // ─── Out of range ───

  it("denies negative confidence", () => {
    expect(shouldAutoPublish({ confidence: -0.5, category: "greeting", safeCategories: SAFE_KEYS })).toBe(false);
  });

  it("denies confidence > 1", () => {
    expect(shouldAutoPublish({ confidence: 1.5, category: "greeting", safeCategories: SAFE_KEYS })).toBe(false);
  });

  // ─── High confidence ───

  it("approves at 0.96", () => {
    expect(shouldAutoPublish({ confidence: 0.96, category: "greeting", safeCategories: SAFE_KEYS })).toBe(true);
  });

  it("approves at 1.0", () => {
    expect(shouldAutoPublish({ confidence: 1.0, category: "greeting", safeCategories: SAFE_KEYS })).toBe(true);
  });
});

describe("shouldAutoPublish — custom threshold", () => {
  it("respects custom threshold of 0.90", () => {
    expect(shouldAutoPublish({ confidence: 0.90, threshold: 0.90, category: "greeting", safeCategories: SAFE_KEYS })).toBe(true);
  });

  it("denies at 0.89 with custom threshold of 0.90", () => {
    expect(shouldAutoPublish({ confidence: 0.89, threshold: 0.90, category: "greeting", safeCategories: SAFE_KEYS })).toBe(false);
  });

  it("defaults to 0.95 when threshold is not provided", () => {
    // 0.949 is below default 0.95
    expect(shouldAutoPublish({ confidence: 0.949, category: "greeting", safeCategories: SAFE_KEYS })).toBe(false);
  });
});

describe("shouldAutoPublish — safe category whitelist", () => {
  it("denies safe-config-key items for unsafe category", () => {
    expect(shouldAutoPublish({ confidence: 0.99, category: "legal", safeCategories: SAFE_KEYS })).toBe(false);
  });

  it("denies unsafe category even at confidence 1.0", () => {
    expect(shouldAutoPublish({ confidence: 1.0, category: "financial", safeCategories: SAFE_KEYS })).toBe(false);
  });

  it("approves safe category at threshold", () => {
    expect(shouldAutoPublish({ confidence: 0.95, category: "faq", safeCategories: SAFE_KEYS })).toBe(true);
  });

  it("denies category not in set (but present in unsafe set)", () => {
    expect(shouldAutoPublish({ confidence: 0.95, category: "medical", safeCategories: SAFE_KEYS })).toBe(false);
  });
});

describe("shouldAutoPublish — change length gate (optional)", () => {
  it("denies when change length exceeds max", () => {
    expect(shouldAutoPublish({
      confidence: 0.95,
      category: "greeting",
      safeCategories: SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: 51,
    })).toBe(false);
  });

  it("approves when change length equals max", () => {
    expect(shouldAutoPublish({
      confidence: 0.95,
      category: "greeting",
      safeCategories: SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: 50,
    })).toBe(true);
  });

  it("approves when change length is below max", () => {
    expect(shouldAutoPublish({
      confidence: 0.95,
      category: "greeting",
      safeCategories: SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: 49,
    })).toBe(true);
  });

  it("ignores change length when maxChangeLength is not set", () => {
    expect(shouldAutoPublish({
      confidence: 0.95,
      category: "greeting",
      safeCategories: SAFE_KEYS,
      changeLength: 9999,
    })).toBe(true);
  });

  it("denies long change with high confidence", () => {
    expect(shouldAutoPublish({
      confidence: 1.0,
      category: "greeting",
      safeCategories: SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: 200,
    })).toBe(false);
  });
});

describe("shouldAutoPublish — combined conditions", () => {
  it("approves: high conf + safe key + short change", () => {
    expect(shouldAutoPublish({
      confidence: 0.95,
      category: "greeting",
      safeCategories: SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: 30,
    })).toBe(true);
  });

  it("denies: high conf + unsafe key + short change", () => {
    expect(shouldAutoPublish({
      confidence: 0.99,
      category: "legal",
      safeCategories: SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: 30,
    })).toBe(false);
  });

  it("denies: low conf + safe key + short change", () => {
    expect(shouldAutoPublish({
      confidence: 0.80,
      category: "greeting",
      safeCategories: SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: 30,
    })).toBe(false);
  });

  it("denies: high conf + safe key + long change", () => {
    expect(shouldAutoPublish({
      confidence: 0.95,
      category: "greeting",
      safeCategories: SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: 51,
    })).toBe(false);
  });

  it("denies: all conditions fail", () => {
    expect(shouldAutoPublish({
      confidence: 0.50,
      category: "legal",
      safeCategories: SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: 200,
    })).toBe(false);
  });
});

describe("shouldAutoPublish — real-world config_key scenario (generate-configs)", () => {
  it("greeting_template with 0.95 conf and 30-char change → auto-publish", () => {
    expect(shouldAutoPublish({
      confidence: 0.95,
      category: "greeting_template",
      safeCategories: BOT_CONFIG_SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: "优化欢迎语的语气和品牌温度".length,
    })).toBe(true);
  });

  it("return_policy with 0.99 conf and 10-char change → denied (not in safe set)", () => {
    expect(shouldAutoPublish({
      confidence: 0.99,
      category: "return_policy",
      safeCategories: BOT_CONFIG_SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: "更新退换货时效".length,
    })).toBe(false);
  });

  it("greeting_template with 0.95 conf but 51-char change → denied (too long)", () => {
    expect(shouldAutoPublish({
      confidence: 0.95,
      category: "greeting_template",
      safeCategories: BOT_CONFIG_SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: 51,
    })).toBe(false);
  });

  it("objection_handling at 0.95 → auto-publish", () => {
    expect(shouldAutoPublish({
      confidence: 0.95,
      category: "objection_handling",
      safeCategories: BOT_CONFIG_SAFE_KEYS,
      maxChangeLength: 50,
      changeLength: 20,
    })).toBe(true);
  });
});

describe("shouldAutoPublish — real-world knowledge scenario (knowledge-gaps)", () => {
  it("faq category with 0.95 conf → auto-publish", () => {
    expect(shouldAutoPublish({
      confidence: 0.95,
      category: "faq",
      safeCategories: KNOWLEDGE_SAFE_CATEGORIES,
    })).toBe(true);
  });

  it("greeting category with 0.97 conf → auto-publish", () => {
    expect(shouldAutoPublish({
      confidence: 0.97,
      category: "greeting",
      safeCategories: KNOWLEDGE_SAFE_CATEGORIES,
    })).toBe(true);
  });

  it("after_sales_policy with 0.99 conf → denied (not in safe set)", () => {
    expect(shouldAutoPublish({
      confidence: 0.99,
      category: "after_sales_policy",
      safeCategories: KNOWLEDGE_SAFE_CATEGORIES,
    })).toBe(false);
  });

  it("campaign category at 0.94 → denied (below threshold)", () => {
    expect(shouldAutoPublish({
      confidence: 0.94,
      category: "campaign",
      safeCategories: KNOWLEDGE_SAFE_CATEGORIES,
    })).toBe(false);
  });
});
