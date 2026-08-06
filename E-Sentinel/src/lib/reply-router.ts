// ============================================================================
// Reply Router — platform-aware reply dispatch with circuit breaker and
// gradual rollout control. Routes CanonicalReply to the correct adapter.
// ============================================================================

import type { CanonicalMessage } from "./types/canonical-message";
import { getAdapter } from "./adapters/registry";
import { getConfigString, getConfigNumber } from "./system-config";
import { sendFeishuNotification } from "./feishu";
import { isEnabled } from "./governance/feature-flags";

/** Dispatch a reply to the appropriate platform adapter */
export async function sendReply(
  canonicalMsg: CanonicalMessage,
  replyText: string,
): Promise<{ method: string; platformMsgId?: string }> {
  const adapter = getAdapter(canonicalMsg.platform_code);

  // ── Feishu fallback: use existing sendFeishuMessage if no adapter registered ──
  if (!adapter) {
    if (canonicalMsg.platform_code === "feishu") {
      const { sendFeishuMessage } = await import("./feishu");
      const chatId = canonicalMsg.reply_context?.chat_id as string || canonicalMsg.session_id;
      const result = await sendFeishuMessage({
        receive_id: chatId,
        receive_id_type: "chat_id",
        content: replyText,
      });
      return { method: result.method };
    }
    console.warn(`[ReplyRouter] No adapter for ${canonicalMsg.platform_code}`);
    return { method: "none" };
  }

  // ── Circuit breaker check ──
  if (adapter.health.isCircuitOpen) {
    console.warn(`[ReplyRouter] Circuit open for ${canonicalMsg.platform_code}`);
    // Fire alert via Feishu
    sendFeishuNotification({
      header: {
        template: "red",
        title: { tag: "plain_text", content: `🔴 ${canonicalMsg.platform_code} 平台熔断器开启` },
      },
      elements: [{
        tag: "div",
        text: {
          tag: "lark_md",
          content: `平台 **${canonicalMsg.platform_code}** 错误率超过阈值，已自动熔断。\n错误率: ${(adapter.health.errorRate * 100).toFixed(1)}%\n平均延迟: ${adapter.health.avgLatencyMs.toFixed(0)}ms\n熔断时间: ${adapter.health.lastTransitionAt}`,
        },
      }],
    }).catch(() => {});
    return { method: "circuit_open" };
  }

  // Feature Flag 集成到 shadow 模式 (events.shadow-mode, QAE-019)
  // 当 flag 启用时，强制走 shadow（用于灰度/实验/紧急降级）
  if (await isEnabled("events.shadow-mode")) {
    return { method: "shadow" };
  }

  // ── Gradual rollout check ──
  const shouldSend = await shouldSendToPlatform(canonicalMsg.platform_code);
  if (!shouldSend) {
    return { method: "shadow" };
  }

  // ── Dispatch ──
  const result = await adapter.sendReply({
    in_reply_to: canonicalMsg,
    content: replyText,
    reply_type: "text",
  });

  return {
    method: result.success ? `${canonicalMsg.platform_code}_api` : "failed",
    platformMsgId: result.messageId,
  };
}

/** Check gradual rollout configuration for a platform */
async function shouldSendToPlatform(platformCode: string): Promise<boolean> {
  const enabled = await getConfigString(`${platformCode}_reply_enabled`, "false");
  if (enabled !== "true") return false;

  const ratio = await getConfigNumber(`${platformCode}_reply_ratio`, 0.1);
  return Math.random() < ratio;
}
