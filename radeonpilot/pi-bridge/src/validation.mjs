const ALLOWED_KEYS = new Set([
  "session_id",
  "environment",
  "telemetry",
  "benchmark",
  "evidence",
  "memory",
  "user_message",
  "role"
]);

export class HttpError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function assertJsonValue(value, path, depth = 0) {
  if (depth > 12) throw new HttpError(400, "invalid_request", `${path} exceeds maximum JSON nesting depth`);
  if (value === null) return;
  const kind = typeof value;
  if (kind === "string" || kind === "number" || kind === "boolean") return;
  if (Array.isArray(value)) {
    if (value.length > 2000) throw new HttpError(400, "invalid_request", `${path} has too many items`);
    value.forEach((item, index) => assertJsonValue(item, `${path}[${index}]`, depth + 1));
    return;
  }
  if (kind === "object") {
    const keys = Object.keys(value);
    if (keys.length > 200) throw new HttpError(400, "invalid_request", `${path} has too many keys`);
    for (const key of keys) assertJsonValue(value[key], `${path}.${key}`, depth + 1);
    return;
  }
  throw new HttpError(400, "invalid_request", `${path} contains unsupported JSON value`);
}

export function validateOrchestrateRequest(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new HttpError(400, "invalid_request", "Request body must be a JSON object");
  }
  for (const key of Object.keys(body)) {
    if (!ALLOWED_KEYS.has(key)) throw new HttpError(400, "invalid_request", `Unknown field: ${key}`);
  }
  if (body.session_id !== undefined && (typeof body.session_id !== "string" || !/^[A-Za-z0-9_.:-]{1,128}$/.test(body.session_id))) {
    throw new HttpError(400, "invalid_request", "session_id must be a 1-128 character identifier");
  }
  for (const key of ["user_message", "role"]) {
    if (body[key] !== undefined && typeof body[key] !== "string") {
      throw new HttpError(400, "invalid_request", `${key} must be a string`);
    }
  }
  for (const key of ["environment", "telemetry", "benchmark", "evidence", "memory"]) {
    if (body[key] !== undefined) assertJsonValue(body[key], key);
  }
  if (!body.environment && !body.telemetry && !body.benchmark && !body.evidence && !body.memory && !body.user_message) {
    throw new HttpError(400, "invalid_request", "At least one of environment, telemetry, benchmark, evidence, memory, or user_message is required");
  }
  return {
    session_id: body.session_id,
    environment: body.environment ?? null,
    telemetry: body.telemetry ?? null,
    benchmark: body.benchmark ?? null,
    evidence: body.evidence ?? null,
    memory: body.memory ?? null,
    user_message: body.user_message ?? "",
    role: body.role ?? "operator"
  };
}
