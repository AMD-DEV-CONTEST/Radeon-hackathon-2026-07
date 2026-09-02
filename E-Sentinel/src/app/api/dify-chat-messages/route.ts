import { getH5RoutingInputs } from "@/lib/h5-routing";

const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const GOFLY_IMAGE_HOST = "goflychat.oss-cn-hangzhou.aliyuncs.com";
const NO_IMAGE_CONTEXT_GUARD =
  "本轮没有附带图片。禁止描述、推断或引用本轮及历史消息中的任何图片；只能依据本轮文字和知识库回答。";

function getDirectBaseUrl() {
  return process.env.H5_DIFY_DIRECT_URL?.trim().replace(/\/+$/, "");
}

function jsonError(message: string, status: number) {
  return Response.json({ code: "dify_proxy_error", message }, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

function isGoFlyImageUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === GOFLY_IMAGE_HOST;
  } catch {
    return false;
  }
}

function extractGoFlyImage(query: string): string | undefined {
  const match = query.trim().match(/^img\[(https?:\/\/[^\]]+)\]$/i);
  return match?.[1];
}

function filenameFromUrl(imageUrl: string): string {
  try {
    const pathname = new URL(imageUrl).pathname;
    const name = pathname.split("/").pop()?.replace(/[^a-zA-Z0-9._-]/g, "") || "gofly-image";
    return /\.[a-z0-9]{2,5}$/i.test(name) ? name : `${name}.jpg`;
  } catch {
    return "gofly-image.jpg";
  }
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

async function uploadRemoteImage(
  baseUrl: string,
  authorization: string,
  user: string,
  imageUrl: string,
): Promise<string> {
  const source = await fetchWithTimeout(imageUrl, { method: "GET" }, DEFAULT_TIMEOUT_MS);
  if (!source.ok) throw new Error(`image source returned ${source.status}`);

  const contentLength = Number(source.headers.get("content-length") || 0);
  if (contentLength > MAX_IMAGE_BYTES) throw new Error("image is too large");
  const bytes = await source.arrayBuffer();
  if (bytes.byteLength > MAX_IMAGE_BYTES) throw new Error("image is too large");

  const contentType = source.headers.get("content-type")?.split(";", 1)[0]?.toLowerCase() || "image/jpeg";
  if (!contentType.startsWith("image/")) throw new Error("image source is not an image");

  const formData = new FormData();
  formData.append("file", new Blob([bytes], { type: contentType }), filenameFromUrl(imageUrl));
  formData.append("user", user);
  const response = await fetchWithTimeout(`${baseUrl}/files/upload`, {
    method: "POST",
    headers: { Authorization: authorization },
    body: formData,
  }, DEFAULT_TIMEOUT_MS);
  if (!response.ok) throw new Error(`Dify image upload returned ${response.status}`);

  const payload = await response.json().catch(() => null) as Record<string, unknown> | null;
  const fileId = typeof payload?.id === "string" ? payload.id.trim() : "";
  if (!fileId) throw new Error("Dify image upload returned no file ID");
  return fileId;
}

export async function POST(request: Request) {
  const baseUrl = getDirectBaseUrl();
  const authorization = request.headers.get("authorization")?.trim();
  if (!baseUrl || !authorization?.toLowerCase().startsWith("bearer ")) {
    return jsonError("Dify proxy is not configured", 503);
  }

  let body: Record<string, unknown>;
  try {
    const parsed = await request.json();
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return jsonError("请求格式不正确", 400);
    body = parsed as Record<string, unknown>;
  } catch {
    return jsonError("请求格式不正确", 400);
  }

  const query = typeof body.query === "string" ? body.query : "";
  const imageUrl = extractGoFlyImage(query);
  const user = typeof body.user === "string" && body.user.trim() ? body.user.trim() : "gofly-visitor";
  const payload = { ...body };
  // GoFly's native page sends streaming and parses Dify SSE events. Keep that
  // mode intact; self-hosted H5 requests use blocking and still receive JSON.
  payload.response_mode = body.response_mode === "streaming" ? "streaming" : "blocking";
  const visitorId = typeof body.visitor_id === "string" ? body.visitor_id.trim().slice(0, 128) : "";
  const visitorName = typeof body.visitor_name === "string" ? body.visitor_name.trim().slice(0, 80) : "";
  const avator = typeof body.avator === "string" ? body.avator.trim().slice(0, 2_000) : "";
  const lang = typeof body.lang === "string" ? body.lang.trim().slice(0, 8) : "";
  const extra = typeof body.extra === "string" ? body.extra.trim().slice(0, 16_000) : "";
  const hasDifyFiles = Array.isArray(payload.files) && payload.files.length > 0;
  payload.inputs = {
    ...(body.inputs && typeof body.inputs === "object" && !Array.isArray(body.inputs) ? body.inputs : {}),
    channel: "h5",
    has_image: Boolean(imageUrl || hasDifyFiles),
    ...(lang ? { lang } : {}),
    ...(visitorId ? { visitor_id: visitorId } : {}),
    ...(visitorName ? { visitor_name: visitorName } : {}),
    ...(avator ? { avator } : {}),
    ...(extra ? { extra } : {}),
    ...getH5RoutingInputs(query),
  };

  // GoFly reuses a visitor conversation, so make the no-image boundary explicit
  // on every text-only turn. This prevents a prior vision turn from becoming an
  // implicit source of facts when the workflow is invoked again.
  if (!imageUrl && !hasDifyFiles && query.trim()) {
    payload.query = `${NO_IMAGE_CONTEXT_GUARD}\n\n用户本轮消息：${query}`;
  }

  if (imageUrl) {
    if (!isGoFlyImageUrl(imageUrl)) return jsonError("不支持的图片来源", 400);
    try {
      const fileId = await uploadRemoteImage(baseUrl, authorization, user, imageUrl);
      payload.query = "请分析这张图片，并只描述图片中可以确认的事实。";
      payload.files = [{ type: "image", transfer_method: "local_file", upload_file_id: fileId }];
    } catch (error) {
      console.error("[DifyProxy] image conversion failed", error);
      return jsonError("图片上传到 Dify 失败，请稍后再试", 502);
    }
  }

  try {
    const response = await fetchWithTimeout(`${baseUrl}/chat-messages`, {
      method: "POST",
      headers: {
        Authorization: authorization,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }, DEFAULT_TIMEOUT_MS);
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") || "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    console.error("[DifyProxy] chat request failed", error);
    return jsonError("Dify 服务暂时不可用，请稍后再试", 502);
  }
}
