// Shared LLM JSON parsing — handles Chinese quotes, markdown fences, trailing commas,
// unmatched braces/brackets, and control characters that LLMs sometimes emit.

function stripMarkdownFences(raw: string): string {
  return raw
    .replace(/```json\s*/gi, "")
    .replace(/```\s*/gi, "")
    .trim();
}

function tryParse(raw: string): unknown | null {
  try { return JSON.parse(raw); } catch { /* continue */ }
  // Remove control characters (except common whitespace)
  const cleaned = raw.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, " ");
  try { return JSON.parse(cleaned); } catch { /* continue */ }
  // Repair trailing commas: ,] → ] and ,} → }
  const noTrailing = cleaned.replace(/,\s*([}\]])/g, "$1");
  try { return JSON.parse(noTrailing); } catch { /* continue */ }
  // Repair unmatched braces/brackets
  const openBraces = (noTrailing.match(/\{/g) || []).length;
  const closeBraces = (noTrailing.match(/\}/g) || []).length;
  const openBrackets = (noTrailing.match(/\[/g) || []).length;
  const closeBrackets = (noTrailing.match(/\]/g) || []).length;
  let repaired = noTrailing;
  if ((repaired.match(/"/g) || []).length % 2 !== 0) repaired += '"';
  // Insert missing closing braces before any trailing bracket (preserve nesting)
  for (let i = closeBraces; i < openBraces; i++) {
    const lastBracket = repaired.lastIndexOf("]");
    if (lastBracket > -1) {
      repaired = repaired.substring(0, lastBracket) + "}" + repaired.substring(lastBracket);
    } else {
      repaired += "}";
    }
  }
  for (let i = closeBrackets; i < openBrackets; i++) repaired += "]";
  try { return JSON.parse(repaired); } catch { /* continue */ }
  return null;
}

/** Parse an LLM response that should contain a JSON object. */
export function parseLlmJson(content: string): Record<string, unknown> | null {
  const raw = stripMarkdownFences(content);
  const objStart = raw.indexOf("{");
  const objEnd = raw.lastIndexOf("}");
  if (objStart === -1) return null;
  const slice = objEnd > objStart ? raw.substring(objStart, objEnd + 1) : raw.substring(objStart);
  return tryParse(slice) as Record<string, unknown> | null;
}

/** Parse an LLM response that should contain a JSON array. */
export function parseLlmJsonArray(content: string): unknown[] | null {
  const raw = stripMarkdownFences(content);
  const arrStart = raw.indexOf("[");
  const arrEnd = raw.lastIndexOf("]");
  if (arrStart === -1) return null;
  // If no closing bracket, feed everything from arrStart so tryParse can append missing ]
  const slice = arrEnd > arrStart ? raw.substring(arrStart, arrEnd + 1) : raw.substring(arrStart);
  return tryParse(slice) as unknown[] | null;
}
