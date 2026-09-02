import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const INJECTION_PATTERNS = ["忽略之前", "system override", "系统提示词", "api 密钥"];
const PRIVACY_PATTERNS = ["银行卡号", "短信验证码", "登录密码", "密码或验证码"];
const SENSITIVE_PATTERNS = [
  "投诉", "赔偿", "315", "举报", "监管", "消费者协会", "工商", "法院", "律师", "起诉",
  "假货", "欺诈", "诈骗", "维权", "曝光",
];
const COMPLIANCE_PATTERNS = [
  "国家级", "最高级", "最佳", "最优", "第一品牌", "独一无二", "顶级", "极品", "全网第一",
  "全球第一", "全国第一", "万能", "全能", "任何环境都能保证",
];
const UNSUPPORTED_CLAIM_PATTERNS = ["保证今天一定", "一定给您", "任何环境都能保证"];
const sourceProvenance = {
  gate_source_sha256_prefix: hashFile(new URL("../src/lib/evaluation/gate.ts", import.meta.url)),
  dataset_source_sha256_prefix: hashFile(new URL("../src/lib/evaluation/dataset.ts", import.meta.url)),
  prompt_config_sha256_prefix: hashFile(new URL("../promptfooconfig.yaml", import.meta.url)),
};

function includesAny(value, patterns) {
  const normalized = value.toLowerCase();
  return patterns.some((pattern) => normalized.includes(pattern.toLowerCase()));
}

function classify(input) {
  if (includesAny(input, INJECTION_PATTERNS)) {
    return { predicted_category: "prompt_injection", blocked: true, evidence_coverage: 1 };
  }
  if (includesAny(input, PRIVACY_PATTERNS)) {
    return { predicted_category: "privacy", blocked: true, evidence_coverage: 1 };
  }
  if (includesAny(input, COMPLIANCE_PATTERNS)) {
    return { predicted_category: "compliance", blocked: true, evidence_coverage: 0.95 };
  }
  if (includesAny(input, UNSUPPORTED_CLAIM_PATTERNS)) {
    return { predicted_category: "unsupported_claim", blocked: true, evidence_coverage: 0.9 };
  }
  if (includesAny(input, SENSITIVE_PATTERNS)) {
    return { predicted_category: "sensitive", blocked: true, evidence_coverage: 1 };
  }
  return { predicted_category: "safe", blocked: false, evidence_coverage: 0.85 };
}

export default class DeterministicFixtureProvider {
  constructor(options = {}) {
    this.providerId = options.id || "fixture-deterministic-v1";
  }

  id() {
    return this.providerId;
  }

  async callApi(prompt, context, options) {
    return callApi(prompt, context, options);
  }
}

export async function callApi(prompt) {
  let request;
  try {
    request = JSON.parse(prompt);
  } catch {
    return { error: "provider prompt must be JSON" };
  }
  if (!request || typeof request.case_id !== "string" || typeof request.input !== "string") {
    return { error: "provider prompt requires case_id and input" };
  }
  const result = classify(request.input);
  return {
    output: JSON.stringify({
      case_id: request.case_id,
      ...result,
      model_version: "fixture-candidate-v1",
      prompt_version: "qa-prompt-v2",
      rule_version: "qa-rules-v1",
      source_provenance: sourceProvenance,
    }),
    latencyMs: 0,
    cost: 0,
  };
}

function hashFile(url) {
  return createHash("sha256").update(readFileSync(url)).digest("hex").slice(0, 16);
}
