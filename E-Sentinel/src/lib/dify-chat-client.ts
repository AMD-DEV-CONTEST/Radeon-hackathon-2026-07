const DEFAULT_TIMEOUT_MS = 15_000;
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export type DifyChatRequest = {
  query: string;
  user: string;
  conversationId?: string;
  inputs?: Record<string, unknown>;
  files?: DifyChatFile[];
};

export type DifyChatFile = {
  type: "image";
  transfer_method: "local_file";
  upload_file_id: string;
};

export type DifyChatResult = {
  answer: string;
  conversationId: string;
  messageId?: string;
};

export class DifyChatError extends Error {
  readonly code: "config" | "timeout" | "upstream" | "invalid_response";
  readonly status?: number;

  constructor(
    message: string,
    code: DifyChatError["code"],
    status?: number,
  ) {
    super(message);
    this.name = "DifyChatError";
    this.code = code;
    this.status = status;
  }
}

function getConfig() {
  const baseUrl = process.env.H5_DIFY_BASE_URL?.trim().replace(/\/+$/, "");
  const apiKey = process.env.H5_DIFY_API_KEY?.trim();

  if (!baseUrl || !apiKey) {
    throw new DifyChatError(
      "Dify chat is not configured",
      "config",
    );
  }

  const timeoutRaw = Number(process.env.H5_DIFY_TIMEOUT_MS || DEFAULT_TIMEOUT_MS);
  const timeoutMs = Number.isFinite(timeoutRaw) && timeoutRaw >= 1_000
    ? Math.min(timeoutRaw, 60_000)
    : DEFAULT_TIMEOUT_MS;

  return { baseUrl, apiKey, timeoutMs };
}

async function parseDifyError(response: Response, fallback: string): Promise<never> {
  throw new DifyChatError(`${fallback} (HTTP ${response.status})`, "upstream", response.status);
}

export async function uploadDifyImage(file: File, user: string): Promise<string> {
  const { baseUrl, apiKey, timeoutMs } = getConfig();
  if (!file.type.startsWith("image/")) {
    throw new DifyChatError("仅支持图片文件", "invalid_response");
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new DifyChatError("图片不能超过 10 MB", "invalid_response");
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const form = new FormData();
    form.append("file", file, file.name || "image.jpg");
    form.append("user", user);
    const response = await fetch(`${baseUrl}/files/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}` },
      body: form,
      signal: controller.signal,
    });
    if (!response.ok) await parseDifyError(response, "Dify 图片上传失败");
    const payload = await response.json().catch(() => null) as Record<string, unknown> | null;
    const id = typeof payload?.id === "string" ? payload.id.trim() : "";
    if (!id) throw new DifyChatError("Dify 图片上传响应无效", "invalid_response");
    return id;
  } catch (error) {
    if (error instanceof DifyChatError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new DifyChatError("Dify 图片上传超时", "timeout");
    }
    throw new DifyChatError("无法上传图片到 Dify", "upstream");
  } finally {
    clearTimeout(timeout);
  }
}

export async function sendDifyChatMessage(
  request: DifyChatRequest,
): Promise<DifyChatResult> {
  const { baseUrl, apiKey, timeoutMs } = getConfig();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${baseUrl}/chat-messages`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        inputs: request.inputs || {},
        query: request.query,
        response_mode: "blocking",
        user: request.user,
        ...(request.conversationId ? { conversation_id: request.conversationId } : {}),
        ...(request.files?.length ? { files: request.files } : {}),
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      // Do not expose Dify's response body: it may contain deployment details.
      throw new DifyChatError(
        `Dify returned HTTP ${response.status}`,
        "upstream",
        response.status,
      );
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new DifyChatError("Dify returned invalid JSON", "invalid_response");
    }

    if (!payload || typeof payload !== "object") {
      throw new DifyChatError("Dify returned an invalid response", "invalid_response");
    }

    const body = payload as Record<string, unknown>;
    const answer = typeof body.answer === "string" ? body.answer.trim() : "";
    const conversationId = typeof body.conversation_id === "string"
      ? body.conversation_id.trim()
      : "";

    if (!answer || !conversationId) {
      throw new DifyChatError("Dify response is missing answer or conversation_id", "invalid_response");
    }

    return {
      answer,
      conversationId,
      messageId: typeof body.message_id === "string" ? body.message_id : undefined,
    };
  } catch (error) {
    if (error instanceof DifyChatError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new DifyChatError("Dify request timed out", "timeout");
    }
    throw new DifyChatError("Unable to reach Dify", "upstream");
  } finally {
    clearTimeout(timeout);
  }
}
