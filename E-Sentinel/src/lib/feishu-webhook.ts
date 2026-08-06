// ============================================================================
// feishu-webhook.ts — inbound webhook: signature verification, decryption, message parsing
// ============================================================================

import crypto from "crypto";

const FEISHU_ENCRYPT_KEY = process.env.FEISHU_EVENT_ENCRYPT_KEY || "";
const FEISHU_VERIFY_TOKEN = process.env.FEISHU_VERIFY_TOKEN || "";

function getAesKey(): Buffer {
  return crypto.createHash("sha256").update(FEISHU_ENCRYPT_KEY).digest();
}

/** Verify X-Lark-Signature header */
export function verifySignature(
  timestamp: string,
  nonce: string,
  body: string,
  signature: string,
): boolean {
  if (!FEISHU_ENCRYPT_KEY) return true; // no key configured → skip verification in dev
  const signStr = `${timestamp}${nonce}${FEISHU_ENCRYPT_KEY}${body}`;
  const expected = crypto.createHash("sha256").update(signStr).digest("hex");
  return expected === signature;
}

/** AES-256-CBC decrypt a Feishu encrypted event body */
export function decryptMessage(encryptedBase64: string): string {
  const key = getAesKey();
  const cipherBuffer = Buffer.from(encryptedBase64, "base64");
  const iv = cipherBuffer.subarray(0, 16);
  const ciphertext = cipherBuffer.subarray(16);

  const decipher = crypto.createDecipheriv("aes-256-cbc", key, iv);
  decipher.setAutoPadding(true);

  const decrypted = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  return decrypted.toString("utf-8");
}

/**
 * Extract readable text from a Feishu message.content JSON string.
 * Handles: text, post (rich text), image, audio, file, sticker, unknown.
 */
export function parseMessageText(msgType: string, contentJson: string): string {
  if (!contentJson) return "[空消息]";

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(contentJson);
  } catch {
    return contentJson;
  }

  switch (msgType) {
    case "text":
      return (parsed.text as string) || "[空文本]";

    case "post": {
      const post = parsed.content;
      if (!post) return "[富文本]";
      try {
        const blocks = post as Record<string, unknown[][]>;
        return Object.values(blocks)
          .flat(2)
          .map((el) => (el as { text?: string })?.text || "")
          .join("");
      } catch {
        return "[富文本]";
      }
    }

    case "image":
      return `[图片]`;

    case "audio":
    case "media":
      return `[语音]`;

    case "file":
      return `[文件: ${(parsed.file_name as string) || ""}]`;

    case "sticker":
      return `[表情]`;

    case "system":
      return `[系统消息]`;

    default:
      return `[不支持的消息类型: ${msgType}]`;
  }
}

/** Validate URL verification token from Feishu handshake */
export function validateToken(token: string): boolean {
  if (!FEISHU_VERIFY_TOKEN) return true; // not configured → skip
  return token === FEISHU_VERIFY_TOKEN;
}

/** Check if webhook environment is configured */
export function isWebhookConfigured(): boolean {
  return Boolean(FEISHU_ENCRYPT_KEY && FEISHU_VERIFY_TOKEN);
}
