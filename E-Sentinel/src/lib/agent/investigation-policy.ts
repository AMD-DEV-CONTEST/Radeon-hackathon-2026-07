/**
 * 服务端调查策略（ADR-0003 第 4 层扩展）：
 * 决定"哪些 case 必须调用哪些工具"，由确定性代码推导，不依赖模型"心情好才调用"。
 *
 * 原则：
 * - 需要政策/产品证据的 finding → 100% 强制检索；
 * - 硬红线（隐私索要/威胁）→ 确定性层直接处置，不做无意义的 RAG（避免"为展示工具而调用"）；
 * - 客户软信号（退款纠纷/产品缺陷）但无违规 → 负责任地检索政策/产品知识核验，但不作为升级依据。
 */
import type { SoftSignalFlag } from "../compliance-engine";

export type RequiredTool = "retrieve_knowledge";

export type FindingType =
  | "false_commitment"
  | "product_accuracy"
  | "refund_policy"
  | "policy_mismatch"
  | "privacy_request"
  | "threat_or_abuse"
  | "service_attitude"
  | "other";

/** 从违规类别/规则文本推断 finding 类型（judge 显式输出 finding_type 时优先）。 */
export function classifyFindingType(category?: string, rule?: string): FindingType {
  const text = `${category || ""} ${rule || ""}`;
  if (/验证码|银行卡|密码|隐私|索要/.test(text)) return "privacy_request";
  if (/威胁|拉黑|辱骂|贬低|拒绝服务/.test(text)) return "threat_or_abuse";
  if (/承诺|虚假|赔付|赔偿|保证/.test(text)) return "false_commitment";
  if (/退款|退货|退差|运费|补偿/.test(text)) return "refund_policy";
  if (/价格|产品|型号|参数|兼容|信息不实|错误的产品/.test(text)) return "product_accuracy";
  if (/政策|规则|流程|标准/.test(text)) return "policy_mismatch";
  if (/服务态度|话术|回应|推诿|敷衍|消极/.test(text)) return "service_attitude";
  return "other";
}

export interface InvestigationPolicyInput {
  /** 语义基线的违规项（含可选的 finding_type）。 */
  baselineViolations: Array<{ category?: string; rule?: string; finding_type?: string }>;
  /** 客户行软信号。 */
  softSignals: SoftSignalFlag[];
  /** 硬红线是否命中（命中则不强制 RAG，避免重复计算）。 */
  hardRedlineHit: boolean;
}

/**
 * 推导必须执行的工具列表。
 * 返回空数组 = 该 case 不强制任何工具（基线或硬红线已足够，Agent 可自由决定）。
 */
export function deriveRequiredTools(opts: InvestigationPolicyInput): RequiredTool[] {
  if (opts.hardRedlineHit) return [];

  const tools = new Set<RequiredTool>();
  for (const v of opts.baselineViolations) {
    const ft = (v.finding_type as FindingType | undefined) || classifyFindingType(v.category, v.rule);
    if (ft === "false_commitment" || ft === "product_accuracy" || ft === "refund_policy" || ft === "policy_mismatch") {
      tools.add("retrieve_knowledge");
    }
  }

  // 客户软信号（退款纠纷/产品缺陷）但基线无违规 → 检索政策/产品知识核验（证据化，不升级）
  const hasEvidenceNeed = opts.softSignals.some(
    (f) => f.code === "refund_dispute" || f.code === "product_defect" || f.code === "logistics_delay"
  );
  if (hasEvidenceNeed && tools.size === 0) {
    tools.add("retrieve_knowledge");
  }

  return [...tools];
}

/**
 * 从会话 + finding 类型推导检索 query（服务端确定性构造，不依赖模型生成）。
 * 优先提取产品型号词（Orbbec 语料），再按 finding 类型拼接主题。
 */
export function deriveRetrievalQuery(
  findingTypes: FindingType[],
  conversation: string,
  defaultQuery = "产品知识库",
): string {
  const model = conversation.match(/Gemini\s*[0-9A-Z]*|Femto\s*[A-Za-z]*|Orbbec|Dabai|Mars|Astra\s*[A-Za-z]*/i)?.[0] || "";
  const prefix = model ? `${model} ` : "";
  if (findingTypes.some((ft) => ft === "refund_policy" || ft === "false_commitment" || ft === "policy_mismatch")) {
    return `${prefix}退款退货政策`;
  }
  if (findingTypes.some((ft) => ft === "product_accuracy")) {
    return `${prefix}产品规格参数`;
  }
  return prefix ? `${prefix}产品知识` : defaultQuery;
}
