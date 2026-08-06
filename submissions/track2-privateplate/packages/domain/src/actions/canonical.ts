import { createHash, randomBytes, timingSafeEqual } from "node:crypto";

/** Stable JSON for hashing: sorted object keys, no whitespace variance. */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(sortValue(value));
}

function sortValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortValue);
  }
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(obj).sort()) {
      sorted[key] = sortValue(obj[key]);
    }
    return sorted;
  }
  return value;
}

export function sha256Hex(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

export function hashPayload(payload: unknown): string {
  return sha256Hex(canonicalJson(payload));
}

export function generateConfirmationToken(): string {
  return randomBytes(32).toString("base64url");
}

export function hashToken(token: string): string {
  return sha256Hex(`pp-token:${token}`);
}

export function safeEqualHex(a: string, b: string): boolean {
  const ba = Buffer.from(a);
  const bb = Buffer.from(b);
  if (ba.length !== bb.length) return false;
  return timingSafeEqual(ba, bb);
}
