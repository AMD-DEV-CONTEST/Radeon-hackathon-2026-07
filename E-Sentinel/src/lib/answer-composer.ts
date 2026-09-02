// ============================================================================
// Unified answer composer / safety gates (inspired by rag-ai-agent)
// Single entry for applying boundaries before final output.
// For qa-system: compliance, no-source, etc. before LLM or response.
// Adapt for Dify deployment: compose before push or in adapter.
// ============================================================================

import { createCorrelationId } from "./correlation";

export interface SafetySignals {
  compliance?: { decision: string; reason?: string };
  noSource?: boolean;
  lowConfidence?: boolean;
  commercialBoundary?: boolean;
}

export function composeFinalAnswer(
  coreAnswer: string,
  signals: SafetySignals,
  lang: "zh" | "en" = "zh",
  correlationId?: string,
): string {
  const corr = correlationId || createCorrelationId();

  if (signals.noSource) {
    return lang === "zh"
      ? `资料中没有足够信息回答此问题。[${corr}]`
      : `Not enough information in sources to answer. [${corr}]`;
  }

  if (signals.compliance && signals.compliance.decision === "block") {
    return lang === "zh"
      ? `此回答因合规原因被拦截：${signals.compliance.reason || "违规"}。[${corr}]`
      : `Answer blocked for compliance: ${signals.compliance.reason || "violation"}. [${corr}]`;
  }

  if (signals.commercialBoundary) {
    return lang === "zh"
      ? `价格/库存/交期等商业信息需人工确认。[${corr}]`
      : `Commercial details (price/stock/delivery) require manual confirmation. [${corr}]`;
  }

  if (signals.lowConfidence) {
    return lang === "zh"
      ? `${coreAnswer}\n\n（置信度较低，建议人工复核）[${corr}]`
      : `${coreAnswer}\n\n(Low confidence, manual review recommended) [${corr}]`;
  }

  return `${coreAnswer} [${corr}]`;
}

// Example usage in evaluate or reply: 
// const final = composeFinalAnswer(parsed.answer, { compliance: result }, 'zh', correlationId);
