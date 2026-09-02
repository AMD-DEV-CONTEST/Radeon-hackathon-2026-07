const VAGUE_ISSUES = new Set([
  "用不了",
  "坏了",
  "不知道",
  "没看见",
  "没有看见",
  "不清楚",
  "有问题",
  "一直不行",
]);

const TRAILING_PUNCTUATION = /[\u3001\u3002\uff0c\uff01\uff1f\uff1a\uff1b\u2026,!.?:;]+$/u;

export const VAGUE_ISSUE_ROUTING_HINT = "vague_issue_clarification";
export const VAGUE_ISSUE_CLARIFICATION =
  "先确认具体表现：打不开、离线、画面黑、没声音、无法绑定或其他；首轮不要同时追问多个排查维度。";

export function normalizeH5ShortMessage(value: string): string {
  return value.trim().toLocaleLowerCase().replace(TRAILING_PUNCTUATION, "");
}

export function isVagueH5Issue(value: string): boolean {
  const normalized = normalizeH5ShortMessage(value);
  return normalized.length <= 20 && VAGUE_ISSUES.has(normalized);
}

export function getH5RoutingInputs(value: string): {
  routing_hint: string;
  clarification_instruction: string;
} {
  if (!isVagueH5Issue(value)) {
    return { routing_hint: "", clarification_instruction: "" };
  }

  return {
    routing_hint: VAGUE_ISSUE_ROUTING_HINT,
    clarification_instruction: VAGUE_ISSUE_CLARIFICATION,
  };
}
