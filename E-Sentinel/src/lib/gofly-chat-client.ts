const DEFAULT_BASE_URL = "https://gofly.v1kf.com";
const DEFAULT_TIMEOUT_MS = 15_000;

export type GoflyChatRequest = {
  visitorId: string;
  content: string;
  visitorName: string;
  avator?: string;
  lang?: string;
  extra?: string;
};

export class GoflyChatError extends Error {
  readonly code: "config" | "timeout" | "upstream" | "invalid_response";
  readonly status?: number;

  constructor(
    message: string,
    code: GoflyChatError["code"],
    status?: number,
  ) {
    super(message);
    this.name = "GoflyChatError";
    this.code = code;
    this.status = status;
  }
}

function getConfig() {
  const baseUrl = (process.env.H5_GOFLY_BASE_URL || DEFAULT_BASE_URL).trim().replace(/\/+$/, "");
  const kefuId = (process.env.H5_GOFLY_KEFU_ID || "conring").trim();
  const entId = (process.env.H5_GOFLY_ENT_ID || "9808").trim();
  const timeoutRaw = Number(process.env.H5_GOFLY_TIMEOUT_MS || DEFAULT_TIMEOUT_MS);
  const timeoutMs = Number.isFinite(timeoutRaw) && timeoutRaw >= 1_000
    ? Math.min(timeoutRaw, 60_000)
    : DEFAULT_TIMEOUT_MS;

  if (!baseUrl || !kefuId || !entId) {
    throw new GoflyChatError("GoFly chat is not configured", "config");
  }

  return { baseUrl, kefuId, entId, timeoutMs };
}

export async function sendGoflyChatMessage(request: GoflyChatRequest): Promise<string> {
  const { baseUrl, kefuId, entId, timeoutMs } = getConfig();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${baseUrl}/api/v1/${encodeURIComponent(entId)}/${encodeURIComponent(kefuId)}/robot/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        visitor_id: request.visitorId,
        content: request.content,
        visitor_name: request.visitorName,
        ...(request.avator ? { avator: request.avator } : {}),
        ...(request.lang ? { lang: request.lang } : {}),
        ...(request.extra ? { extra: request.extra } : {}),
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new GoflyChatError(`GoFly returned HTTP ${response.status}`, "upstream", response.status);
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new GoflyChatError("GoFly returned invalid JSON", "invalid_response");
    }

    if (!payload || typeof payload !== "object") {
      throw new GoflyChatError("GoFly returned an invalid response", "invalid_response");
    }

    const body = payload as { code?: unknown; result?: { content?: unknown } };
    const answer = typeof body.result?.content === "string" ? body.result.content.trim() : "";
    if (body.code !== 20000 || !answer) {
      throw new GoflyChatError("GoFly response is missing content", "invalid_response");
    }

    return answer;
  } catch (error) {
    if (error instanceof GoflyChatError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new GoflyChatError("GoFly request timed out", "timeout");
    }
    throw new GoflyChatError("Unable to reach GoFly", "upstream");
  } finally {
    clearTimeout(timeout);
  }
}
