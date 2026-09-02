// ============================================================================
// Tmall Platform Adapter — TOP (Taobao Open Platform) integration.
// Implements PlatformAdapter interface for Tmall customer service messages.
//
// Protocol: HTTP POST webhook with MD5 signature verification.
// Auth: OAuth 2.0 authorization_code → access_token (7d) + refresh_token (30d).
// Timeout: 5 seconds (Tmall requires ack within this window).
// ============================================================================

import { createHash } from "crypto";
import type { CanonicalMessage, CanonicalReply } from "../types/canonical-message";
import type { PlatformAdapter } from "./types";
import { CircuitBreaker } from "./circuit-breaker";
import { getDb } from "./db";

// ── Types ──

interface TmallWebhookPayload {
  msg_id: string;
  session_id: string;
  chat_id?: string;
  msg_type: "text" | "image" | "mixed" | "system" | "file";
  content?: Record<string, unknown>;
  sender_user_id?: string;
  buyer_nick?: string;
  seller_nick?: string;
  send_time: string;
  sign?: string;
  sign_method?: string;
}

interface TmallTokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;       // seconds until access_token expires
  re_expires_in: number;    // seconds until refresh_token expires
}

// ── Constants ──

const TMALL_TOKEN_URL = "https://oauth.taobao.com/token";
const TMALL_API_BASE = "https://eco.taobao.com/router/rest";

let _appKey = "";
let _appSecret = "";

function getAppKey(): string {
  if (!_appKey) _appKey = process.env.TMALL_APP_KEY || "";
  return _appKey;
}

function getAppSecret(): string {
  if (!_appSecret) _appSecret = process.env.TMALL_APP_SECRET || "";
  return _appSecret;
}

// ── Signature Verification ──

function verifyTmallSignature(
  queryParams: Record<string, string>,
  body: string,
): boolean {
  const appSecret = getAppSecret();
  if (!appSecret) return true; // not configured — skip in dev

  const sign = queryParams.sign;
  if (!sign) return false;

  const sortedStr = Object.keys(queryParams)
    .filter((k) => k !== "sign" && k !== "sign_method")
    .sort()
    .map((k) => `${k}${queryParams[k]}`)
    .join("");

  const computed = createHash("md5")
    .update(`${appSecret}${sortedStr}${body}${appSecret}`, "utf8")
    .digest("hex")
    .toUpperCase();

  return computed === sign;
}

// ── Message Normalization ──

function extractTmallText(raw: TmallWebhookPayload): string {
  const content = raw.content || {};

  switch (raw.msg_type) {
    case "text":
      return (content.text as string) || "";
    case "mixed": {
      const items = content.items as Array<{ type: string; text?: string }> | undefined;
      return items
        ?.filter((i) => i.type === "text")
        .map((i) => i.text || "")
        .join(" ") || "[混合消息]";
    }
    case "image":
      return "[图片]";
    case "file":
      return "[文件]";
    case "system":
      return "[系统消息]";
    default:
      return `[不支持的消息类型: ${raw.msg_type}]`;
  }
}

function tmallToCanonical(raw: TmallWebhookPayload): CanonicalMessage {
  return {
    platform_message_id: raw.msg_id,
    platform_code: "tmall",
    session_id: raw.session_id,
    customer_id: raw.sender_user_id || raw.buyer_nick || "unknown",
    content: extractTmallText(raw),
    message_type: raw.msg_type,
    timestamp: new Date(raw.send_time).toISOString(),
    reply_context: {
      tmall_session_id: raw.session_id,
      tmall_chat_id: raw.chat_id,
      seller_nick: raw.seller_nick,
    },
  };
}

// ── OAuth Token Management ──

async function getTmallAccessToken(): Promise<string | null> {
  const db = await getDb();
  if (!db) return null;

  const tmallPlatformId = await resolveTmallPlatformId(db);
  if (!tmallPlatformId) return null;

  // Check cached token
  const { data: existing } = await db
    .from("platform_credentials")
    .select("credential_value, expires_at")
    .eq("platform_id", tmallPlatformId)
    .eq("credential_key", "access_token")
    .maybeSingle();

  if (existing && existing.expires_at && new Date(existing.expires_at) > new Date(Date.now() + 300_000)) {
    return existing.credential_value as string;
  }

  // Refresh using refresh_token
  const { data: refreshRow } = await db
    .from("platform_credentials")
    .select("credential_value")
    .eq("platform_id", tmallPlatformId)
    .eq("credential_key", "refresh_token")
    .maybeSingle();

  if (!refreshRow) {
    console.warn("[Tmall] No refresh_token configured — run OAuth authorization flow first");
    return null;
  }

  try {
    const res = await fetch(TMALL_TOKEN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: getAppKey(),
        client_secret: getAppSecret(),
        refresh_token: refreshRow.credential_value as string,
      }),
    });

    if (!res.ok) {
      console.error("[Tmall] Token refresh failed:", res.status);
      return null;
    }

    const tokens: TmallTokenResponse = await res.json();

    // Atomically update both tokens
    const now = Date.now();
    await db.from("platform_credentials").upsert([
      {
        platform_id: tmallPlatformId,
        credential_key: "access_token",
        credential_value: tokens.access_token,
        expires_at: new Date(now + tokens.expires_in * 1000).toISOString(),
        updated_at: new Date().toISOString(),
      },
      {
        platform_id: tmallPlatformId,
        credential_key: "refresh_token",
        credential_value: tokens.refresh_token,
        expires_at: new Date(now + tokens.re_expires_in * 1000).toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]);

    return tokens.access_token;
  } catch (err) {
    console.error("[Tmall] Token refresh error:", String(err).slice(0, 100));
    return null;
  }
}

async function resolveTmallPlatformId(
  db: NonNullable<Awaited<ReturnType<typeof getDb>>>,
): Promise<string | null> {
  const { data: existing } = await db
    .from("platforms")
    .select("id")
    .eq("code", "tmall")
    .maybeSingle();

  if (existing) return existing.id as string;

  // Auto-create if not exists
  const { data: created, error } = await db
    .from("platforms")
    .insert({ name: "天猫", code: "tmall", bot_type: "third_party" })
    .select("id")
    .single();

  if (error) {
    console.error("[Tmall] Failed to create platform:", error.message);
    return null;
  }
  return created.id as string;
}

// ── Adapter Implementation ──

const circuitBreaker = new CircuitBreaker({
  errorRateThreshold: 0.05,
  cooldownMs: 300_000,
});

export const tmallAdapter: PlatformAdapter = {
  platformCode: "tmall",

  async verifyAndNormalize(
    _headers: Headers,
    rawBody: string,
    queryParams: Record<string, string>,
  ): Promise<CanonicalMessage> {
    // 1. Verify signature (only if app secret is configured)
    if (getAppSecret() && !verifyTmallSignature(queryParams, rawBody)) {
      circuitBreaker.record(false, 0);
      throw new Error("Invalid Tmall signature");
    }

    // 2. Parse payload
    let raw: TmallWebhookPayload;
    try {
      raw = JSON.parse(rawBody) as TmallWebhookPayload;
    } catch {
      throw new Error("Invalid JSON body");
    }

    if (!raw.msg_id || !raw.session_id) {
      throw new Error("Missing required fields: msg_id, session_id");
    }

    // 3. Convert to canonical message
    circuitBreaker.record(true, 0);
    return tmallToCanonical(raw);
  },

  async sendReply(reply: CanonicalReply): Promise<{ success: boolean; messageId?: string }> {
    const startTime = Date.now();
    const token = await getTmallAccessToken();
    if (!token) {
      circuitBreaker.record(false, Date.now() - startTime);
      return { success: false };
    }

    try {
      const ctx = reply.in_reply_to.reply_context;
      const res = await fetch(TMALL_API_BASE, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          method: "taobao.openim.message.send",
          app_key: getAppKey(),
          session: token,
          timestamp: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
          format: "json",
          v: "2.0",
          sign_method: "md5",
          to_user_id: reply.in_reply_to.customer_id,
          session_id: ctx.tmall_session_id as string,
          chat_id: (ctx.tmall_chat_id as string) || "",
          content: JSON.stringify({ text: reply.content }),
          msg_type: "text",
        }),
      });

      const elapsed = Date.now() - startTime;
      if (res.ok) {
        const data = await res.json() as Record<string, unknown>;
        circuitBreaker.record(true, elapsed);
        return { success: true, messageId: data.msg_id as string };
      }

      circuitBreaker.record(false, elapsed);
      console.warn("[Tmall] Reply send failed:", res.status);
      return { success: false };
    } catch (err) {
      circuitBreaker.record(false, Date.now() - startTime);
      console.error("[Tmall] Reply send error:", String(err).slice(0, 100));
      return { success: false };
    }
  },

  async refreshAuth(): Promise<void> {
    await getTmallAccessToken();
  },

  get health() {
    return circuitBreaker.health;
  },
};
