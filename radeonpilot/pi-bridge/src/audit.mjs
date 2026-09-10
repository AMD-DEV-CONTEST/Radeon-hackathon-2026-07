import { createHash } from "node:crypto";
import { mkdir, appendFile } from "node:fs/promises";
import { dirname } from "node:path";

const SENSITIVE_KEY = /(authorization|api[_-]?key|password|secret|token|credential)/i;

function hashValue(value) {
  return createHash("sha256").update(String(value)).digest("hex").slice(0, 16);
}

function summarize(value, depth = 0) {
  if (value === null || value === undefined) return value;
  if (typeof value === "string") {
    return { type: "string", length: value.length, sha256_16: hashValue(value) };
  }
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (Array.isArray(value)) {
    return { type: "array", length: value.length, sample: depth < 2 ? value.slice(0, 3).map((item) => summarize(item, depth + 1)) : undefined };
  }
  if (typeof value === "object") {
    const entries = Object.entries(value).slice(0, 20);
    return Object.fromEntries(entries.map(([key, item]) => [key, SENSITIVE_KEY.test(key) ? "[REDACTED]" : summarize(item, depth + 1)]));
  }
  return { type: typeof value };
}

export async function writeAudit(config, event) {
  const record = {
    ts: new Date().toISOString(),
    type: event.type,
    request_id: event.requestId,
    session_id: event.sessionId,
    ok: event.ok,
    status: event.status,
    duration_ms: event.durationMs,
    remote: event.remote,
    body: event.body ? summarize(event.body) : undefined,
    error: event.error ? { code: event.error.code, message: summarize(event.error.message) } : undefined
  };
  await mkdir(dirname(config.auditLogPath), { recursive: true });
  await appendFile(config.auditLogPath, `${JSON.stringify(record)}\n`, "utf8");
}
