import type { AgentIntent, AgentToolName, GraphPhase } from "./state.js";
import { AGENT_TOOL_ALLOWLIST, PHASE_ALLOWED_TOOLS } from "./state.js";

const MEDICAL_RISK_PATTERNS = [
  /诊断/,
  /确诊/,
  /处方/,
  /开药/,
  /调药/,
  /停药/,
  /用药剂量/,
  /药剂量/,
  /降糖药/,
  /血糖用药/,
  /胰岛素/,
  /治好/,
  /根治/,
  /代替医生/
];

const WRITE_SCOPE_PATTERNS = [
  /删除成员/,
  /真实下单/,
  /直接下单/,
  /真实发送/,
  /直接发(?:微信|消息)/,
  /绕过确认/,
  /写入外部系统/
];

export type PolicyDecision = {
  intent: AgentIntent;
  allowContinue: boolean;
  safeStop: boolean;
  userMessage?: string;
  injectionFlag: boolean;
};

/**
 * Hard safety gate for the model-routed path.
 * Only handles boundaries that must never reach the model:
 * - medical risk (diagnosis, prescription, medication changes)
 * - out-of-scope writes (real external writes, data modification)
 * - prompt injection attempts
 *
 * Business intent classification (plan/revise/inspect/handoff) is owned by
 * the model decision loop, not by regex.
 */
export type HardSafetyDecision =
  | { allowed: true }
  | { allowed: false; reason: "medical_risk" | "out_of_scope_write" | "prompt_injection"; userMessage: string };

export function hardSafetyGate(userText: string): HardSafetyDecision {
  const text = userText.trim();
  const injectionFlag = /ignore previous|忽略以上|系统提示|tool_call|<\/?system>/i.test(
    text
  );

  if (injectionFlag) {
    return {
      allowed: false,
      reason: "prompt_injection",
      userMessage:
        "检测到试图改变系统规则或工具权限的内容，本轮已安全停止。你可以重新描述正常的家庭配餐需求。"
    };
  }

  if (MEDICAL_RISK_PATTERNS.some((p) => p.test(text))) {
    return {
      allowed: false,
      reason: "medical_risk",
      userMessage:
        "我不能提供诊断、处方或调药建议。请咨询具备资质的医护人员。我可以继续帮你做非医疗的家庭配餐协调。"
    };
  }

  if (WRITE_SCOPE_PATTERNS.some((p) => p.test(text))) {
    return {
      allowed: false,
      reason: "out_of_scope_write",
      userMessage:
        "我不能代替你向外部系统下单或发送，也不能绕过确认直接写入。可以先生成库存、家庭资料或任务卡预览，再由你在可信入口确认。"
    };
  }

  return { allowed: true };
}

/**
 * Legacy regex-based intent classifier for the deterministic demo path only.
 * The model-routed path uses hardSafetyGate + model decision instead.
 */
export function classifyIntent(userText: string): PolicyDecision {
  const text = userText.trim();
  const injectionFlag = /ignore previous|忽略以上|系统提示|tool_call|<\/?system>/i.test(
    text
  );

  if (MEDICAL_RISK_PATTERNS.some((p) => p.test(text))) {
    return {
      intent: "medical_risk",
      allowContinue: false,
      safeStop: true,
      injectionFlag,
      userMessage:
        "我不能提供诊断、处方或调药建议。请咨询具备资质的医护人员。我可以继续帮你做非医疗的家庭配餐协调。"
    };
  }

  if (WRITE_SCOPE_PATTERNS.some((p) => p.test(text))) {
    return {
      intent: "out_of_scope_write",
      allowContinue: false,
      safeStop: false,
      injectionFlag,
      userMessage:
        "我不能代替你向外部系统下单或发送，也不能绕过确认直接写入。可以先生成库存、家庭资料或任务卡预览，再由你在可信入口确认。"
    };
  }

  // Knowledge / policy questions before handoff — "任务卡能不能写疾病" is RAG, not send.
  if (
    /为什么|依据|规则|知识库|检索|能不能写疾病|最小披露|不编数字|不打分|winner|来源|疾病名|隐私|披露/.test(
      text
    )
  ) {
    return {
      intent: "retrieve_guidance",
      allowContinue: true,
      safeStop: false,
      injectionFlag
    };
  }

  // Inventory restock / buy language — before meal planning phrases.
  if (
    /买了|采购了|入库|补了|刚买|两盒|一盒豆腐|补充库存|进货/.test(text)
  ) {
    return {
      intent: "inspect_context",
      allowContinue: true,
      safeStop: false,
      injectionFlag
    };
  }

  if (
    /发给保姆|发给家政|发送任务|交给保姆|handoff|发给执行|任务卡|预览.*任务|准备发送/.test(
      text
    )
  ) {
    return { intent: "handoff_task", allowContinue: true, safeStop: false, injectionFlag };
  }

  // Initial planning phrases win over "don't want X" constraints in the same utterance.
  if (
    /吃什么|配餐|规划|安排.*餐|来一顿|帮我安排/.test(text) ||
    (/中午|午餐|晚饭|晚餐|今晚/.test(text) && /吃|餐|安排/.test(text))
  ) {
    return { intent: "plan_meal", allowContinue: true, safeStop: false, injectionFlag };
  }

  if (
    /更省事|尽量省事|省事一点|简单一点|简单点|少折腾|快手/.test(text) ||
    (/不要|不想|换一道|拒绝|去掉|别做|不要再|重规划|改成|换一/.test(text) &&
      (/菜|蛋|鸡|豆腐|饭|餐|计划|蒸蛋/.test(text) || /换/.test(text)))
  ) {
    return { intent: "revise_meal", allowContinue: true, safeStop: false, injectionFlag };
  }

  if (/库存|家里有什么|家庭成员|谁在家|查看家庭|冰箱/.test(text)) {
    return { intent: "inspect_context", allowContinue: true, safeStop: false, injectionFlag };
  }

  return {
    intent: "unknown",
    allowContinue: false,
    safeStop: false,
    injectionFlag,
    userMessage: "我可以帮你查看家庭库存、规划一顿共享餐、按你的拒绝重规划，或预览发给保姆的任务卡。请用中文描述需求。"
  };
}

export function assertToolAllowed(
  phase: GraphPhase,
  tool: string,
  /**
   * Precomputed domain tools from computeAvailableActions().
   * When provided, this is the single authorization source.
   */
  availableDomainTools?: readonly AgentToolName[]
): { ok: true; tool: AgentToolName } | { ok: false; code: "RISK_GUARD_TRIGGERED"; message: string } {
  if (tool.startsWith("commit_")) {
    return {
      ok: false,
      code: "RISK_GUARD_TRIGGERED",
      message: "Agent 不得调用 commit 工具；确认发送只能由 UI/CLI 侧通道完成。"
    };
  }
  if (!(AGENT_TOOL_ALLOWLIST as readonly string[]).includes(tool)) {
    return {
      ok: false,
      code: "RISK_GUARD_TRIGGERED",
      message: `工具不在 allowlist：${tool}`
    };
  }
  if (availableDomainTools) {
    if (!availableDomainTools.includes(tool as AgentToolName)) {
      return {
        ok: false,
        code: "RISK_GUARD_TRIGGERED",
        message: `当前状态不允许工具：${tool}`
      };
    }
    return { ok: true, tool: tool as AgentToolName };
  }
  const allowed = PHASE_ALLOWED_TOOLS[phase];
  if (!allowed.includes(tool as AgentToolName)) {
    return {
      ok: false,
      code: "RISK_GUARD_TRIGGERED",
      message: `当前阶段 ${phase} 不允许工具 ${tool}`
    };
  }
  return { ok: true, tool: tool as AgentToolName };
}
