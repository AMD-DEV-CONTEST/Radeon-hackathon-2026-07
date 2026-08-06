/**
 * Hard capability boundary for actions the Agent must never pretend to do.
 * Complements hardSafetyGate: not medical/write-scope, but product red lines
 * (chat-confirm send, stale preview reuse).
 */
import type { AgentState } from "./state.js";
import type { AgentGoal } from "./contracts.js";

export type CapabilityBoundaryHit = {
  reasonCode: "CONFIRMATION_REQUIRED" | "STALE_CONTEXT";
  goal: AgentGoal;
  message: string;
};

/**
 * Returns a refuse decision when the user asks the chat channel to do something
 * only the trusted UI side-channel may do.
 */
export function capabilityBoundaryGate(
  userText: string,
  state: Pick<
    AgentState,
    "phase" | "pendingActionId" | "activePlanId" | "confirmationStatus"
  >
): CapabilityBoundaryHit | null {
  const text = userText.trim();
  if (!text) return null;

  // Chat "confirm & send" / "call the send tool" — never a Domain tool.
  const wantsChatCommit =
    /直接(调用)?发送|直接.*(发给|发送)|别问了.*发|替我发(给|送)|调用发送工具|聊天里.*确认|我说确认|确认了.*发送|直接发送|用.*确认信息.*发送|旧任务卡.*确认|旧确认|刚才.*确认信息/.test(
      text
    );

  if (!wantsChatCommit) return null;

  // Explicit stale / old card language → STALE_CONTEXT.
  const staleLanguage =
    /旧任务卡|旧确认|刚才.*确认信息|用刚才|过期|已失效|作废/.test(text);

  if (staleLanguage) {
    return {
      reasonCode: "STALE_CONTEXT",
      goal: "send_handoff",
      message:
        "当前没有有效的待确认任务卡，或你引用的是已失效的旧预览。聊天里不能代发；请先重新预览任务卡，再在可信确认入口完成发送。"
    };
  }

  // Any chat-channel "just send it" request is CONFIRMATION_REQUIRED —
  // whether or not a live preview exists. Real send is UI/CLI only.
  return {
    reasonCode: "CONFIRMATION_REQUIRED",
    goal: "send_handoff",
    message:
      "我只能生成任务卡预览，不能在聊天里执行最终发送。请在界面的确认按钮完成发送；聊天中的「确认」不会触发发送。"
  };
}
