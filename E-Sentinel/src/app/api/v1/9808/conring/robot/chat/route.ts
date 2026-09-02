import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { DifyChatError, sendDifyChatMessage, uploadDifyImage } from "@/lib/dify-chat-client";
import { getH5RoutingInputs } from "@/lib/h5-routing";

const VISITOR_COOKIE = "h5_visitor_id";
const CONVERSATION_COOKIE = "h5_dify_conversation_id";
const MAX_CONTENT_LENGTH = 4_000;
const MAX_NAME_LENGTH = 80;
const MAX_EXTRA_LENGTH = 16_000;
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const ALLOWED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);
const RATE_LIMIT_WINDOW_MS = 60_000;
const RATE_LIMIT_MAX = 30;
const H5_DEPLOYMENT_HEADER = "dify-h5-v1";
const H5_NO_STORE_HEADERS = {
  "Cache-Control": "no-store",
  "X-H5-Deployment": H5_DEPLOYMENT_HEADER,
};

type RateEntry = { count: number; resetAt: number };
const rateEntries = new Map<string, RateEntry>();

function isRateLimited(key: string): boolean {
  const now = Date.now();
  const current = rateEntries.get(key);
  if (!current || current.resetAt <= now) {
    rateEntries.set(key, { count: 1, resetAt: now + RATE_LIMIT_WINDOW_MS });
    if (rateEntries.size > 2_000) {
      for (const [entryKey, entry] of rateEntries) {
        if (entry.resetAt <= now) rateEntries.delete(entryKey);
      }
    }
    return false;
  }

  current.count += 1;
  return current.count > RATE_LIMIT_MAX;
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value.trim() : fallback;
}

function badRequest(message: string) {
  return NextResponse.json({ error: message }, { status: 400, headers: H5_NO_STORE_HEADERS });
}

function requestUsesHttps(request: Request): boolean {
  const forwardedProto = request.headers.get("x-forwarded-proto")?.split(",", 1)[0]?.trim().toLowerCase();
  return forwardedProto === "https" || new URL(request.url).protocol === "https:";
}

export async function POST(request: Request) {
  const forwardedFor = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  const rateKey = forwardedFor || request.headers.get("x-real-ip") || "anonymous";
  if (isRateLimited(rateKey)) {
    return NextResponse.json(
      { error: "请求过于频繁，请稍后再试" },
      { status: 429, headers: { ...H5_NO_STORE_HEADERS, "Retry-After": "60" } },
    );
  }

  let body: Record<string, unknown>;
  let image: File | undefined;
  try {
    const contentType = request.headers.get("content-type") || "";
    if (contentType.toLowerCase().includes("multipart/form-data")) {
      const form = await request.formData();
      body = Object.fromEntries(["content", "visitor_id", "visitor_name", "lang", "avator", "extra"].map((key) => [key, form.get(key)]));
      const candidate = form.get("image") || form.get("file");
      if (candidate instanceof File && candidate.size > 0) image = candidate;
    } else {
      const parsed = await request.json();
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return badRequest("请求格式不正确");
      body = parsed as Record<string, unknown>;
    }
  } catch {
    return badRequest("请求格式不正确");
  }

  const hasImage = Boolean(image);
  const content = text(body.content, hasImage ? "请分析这张图片中的摄像头问题。" : "");
  if (!content) return badRequest("content 不能为空");
  if (content.length > MAX_CONTENT_LENGTH) return badRequest(`content 不能超过 ${MAX_CONTENT_LENGTH} 个字符`);

  const visitorId = text(body.visitor_id).slice(0, 128) || crypto.randomUUID();
  const visitorName = text(body.visitor_name, "访客").slice(0, MAX_NAME_LENGTH);
  const lang = ["cn", "en", "tw", "jp", "ru", "kr"].includes(text(body.lang, "cn"))
    ? text(body.lang, "cn")
    : "cn";
  const avator = text(body.avator).slice(0, 2_000);
  const extra = text(body.extra).slice(0, MAX_EXTRA_LENGTH);
  if (image && (!ALLOWED_IMAGE_TYPES.has(image.type) || image.size > MAX_IMAGE_BYTES)) {
    return badRequest("仅支持 10 MB 以内的 JPG、PNG、WEBP 或 GIF 图片");
  }

  const cookieStore = await cookies();
  const previousConversationId = cookieStore.get(CONVERSATION_COOKIE)?.value;

  try {
    const uploadFileId = image ? await uploadDifyImage(image, visitorId) : undefined;
    const result = await sendDifyChatMessage({
      query: content,
      user: visitorId,
      conversationId: previousConversationId,
      inputs: {
        channel: "h5",
        lang,
        visitor_id: visitorId,
        visitor_name: visitorName,
        ...getH5RoutingInputs(content),
        ...(avator ? { avator } : {}),
        ...(extra ? { extra } : {}),
        has_image: Boolean(uploadFileId),
      },
      ...(uploadFileId ? { files: [{ type: "image", transfer_method: "local_file", upload_file_id: uploadFileId }] } : {}),
    });

    const response = NextResponse.json(
      {
        answer: result.answer,
        content: result.answer,
        conversation_id: result.conversationId,
        message_id: result.messageId,
      },
      { headers: H5_NO_STORE_HEADERS },
    );
    // Direct IP testing is HTTP, while the future GoFly reverse proxy is HTTPS.
    // Use the actual request context so HTTP can retain a test conversation and
    // HTTPS still gets a Secure cookie in production.
    const secure = requestUsesHttps(request);
    response.cookies.set(VISITOR_COOKIE, visitorId, {
      httpOnly: true,
      sameSite: "lax",
      secure,
      maxAge: 60 * 60 * 24 * 30,
      path: "/",
    });
    response.cookies.set(CONVERSATION_COOKIE, result.conversationId, {
      httpOnly: true,
      sameSite: "lax",
      secure,
      maxAge: 60 * 60 * 24,
      path: "/",
    });
    return response;
  } catch (error) {
    if (error instanceof DifyChatError) {
      const status = error.code === "config" ? 503 : error.code === "timeout" ? 504 : 502;
      return NextResponse.json(
        { error: error.code === "config" ? "客服服务尚未配置" : "客服服务暂时不可用，请稍后再试" },
        { status, headers: H5_NO_STORE_HEADERS },
      );
    }
    console.error("[H5Chat] unexpected error", error);
    return NextResponse.json(
      { error: "客服服务暂时不可用，请稍后再试" },
      { status: 502, headers: H5_NO_STORE_HEADERS },
    );
  }
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true }, { headers: H5_NO_STORE_HEADERS });
  response.cookies.set(CONVERSATION_COOKIE, "", { maxAge: 0, path: "/" });
  return response;
}
