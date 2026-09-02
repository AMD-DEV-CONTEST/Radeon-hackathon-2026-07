// ============================================================================
// Knowledge Import Utilities — shared parsing helpers for import flows
// ============================================================================

export const VALID_CATEGORIES = ["product", "faq", "after_sales_policy", "campaign", "greeting"] as const;

const CATEGORY_MAP: Record<string, string> = {
  "物流": "faq", "产品": "product", "售后": "after_sales_policy",
  "政策": "after_sales_policy", "通用": "faq", "活动": "campaign", "欢迎语": "greeting",
  "商品": "product", "订单": "faq", "退换货": "after_sales_policy",
  "退款": "after_sales_policy", "发货": "faq", "优惠": "campaign",
};

/** Map Chinese category labels to DB enum values; defaults to "faq" */
export function resolveCategory(label: string | undefined): string {
  if (!label) return "faq";
  const mapped = CATEGORY_MAP[label.trim()];
  if (mapped && (VALID_CATEGORIES as readonly string[]).includes(mapped)) return mapped;
  const lower = label.trim().toLowerCase();
  if ((VALID_CATEGORIES as readonly string[]).includes(lower)) return lower;
  return "faq";
}

/** Parse JSON array from raw LLM output, stripping markdown code fences */
export function parseImportJSON(content: string): Record<string, unknown>[] {
  const raw = content.replace(/```json\s*/gi, "").replace(/```\s*/gi, "").trim();
  const arrStart = raw.indexOf("[");
  const arrEnd = raw.lastIndexOf("]");
  if (arrStart !== -1 && arrEnd !== -1 && arrEnd > arrStart) {
    try { return JSON.parse(raw.substring(arrStart, arrEnd + 1)); } catch { /* fall through */ }
  }
  return [];
}

/** Parse JSON with catch-all fallback (also tries bare JSON.parse on full string) */
export function parseJsonEntries(content: string): Record<string, unknown>[] {
  const raw = content.replace(/```json\s*/gi, "").replace(/```\s*/gi, "").trim();
  const arrStart = raw.indexOf("[");
  const arrEnd = raw.lastIndexOf("]");
  if (arrStart !== -1 && arrEnd !== -1 && arrEnd > arrStart) {
    try { return JSON.parse(raw.substring(arrStart, arrEnd + 1)); } catch { /* fall through */ }
  }
  try { return JSON.parse(raw); } catch { return []; }
}

/** Parse CSV with header row: title,content,category,keywords */
export function parseCsvEntries(text: string): Record<string, unknown>[] {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  if (lines.length < 2) return [];

  const header = lines[0].toLowerCase().split(",").map((h) => h.trim());
  const titleIdx = header.indexOf("title");
  const contentIdx = header.indexOf("content");
  const categoryIdx = header.indexOf("category");
  const keywordsIdx = header.indexOf("keywords");

  if (titleIdx === -1 || contentIdx === -1) return [];

  const entries: Record<string, unknown>[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(",").map((c) => c.trim().replace(/^"(.*)"$/, "$1"));
    const entry: Record<string, unknown> = {
      title: cols[titleIdx] || "",
      content: cols[contentIdx] || "",
      category: categoryIdx !== -1 ? cols[categoryIdx] || "faq" : "faq",
    };
    if (keywordsIdx !== -1 && cols[keywordsIdx]) {
      entry.keywords = cols[keywordsIdx].split(";").map((k) => k.trim()).filter(Boolean);
    }
    if (entry.title && entry.content) entries.push(entry);
  }
  return entries;
}
