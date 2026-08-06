export interface UnresolvedQuestionInput {
  session_id?: unknown;
  platform_code?: unknown;
  channel?: unknown;
  user_question?: unknown;
  ai_reply?: unknown;
  category?: unknown;
  issue_type?: unknown;
  transfer_reason?: unknown;
  unresolved_reason?: unknown;
  checked_steps?: unknown;
  conversation?: unknown;
  priority?: unknown;
  satisfaction?: unknown;
  note?: unknown;
  tags?: unknown;
}

export interface UnresolvedExportRow {
  id?: unknown;
  session_id?: unknown;
  platform_code?: unknown;
  user_question?: unknown;
  ai_reply?: unknown;
  transfer_reason?: unknown;
  conversation?: unknown;
  category?: unknown;
  status?: unknown;
  created_at?: unknown;
}

export function cleanText(value: unknown, maxLength = 2000): string {
  if (value === null || value === undefined) return "";
  return String(value).trim().slice(0, maxLength);
}

export function normalizeCheckedSteps(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => cleanText(item, 200)).filter(Boolean);
  }

  const text = cleanText(value, 2000);
  if (!text) return [];

  return text
    .split(/\r?\n|[;；]/)
    .map((line) => line.replace(/^\s*(?:[-*]|\d+[.、)])\s*/, "").trim())
    .filter(Boolean);
}

export function buildConversationText(input: UnresolvedQuestionInput): string {
  const existingConversation = cleanText(input.conversation, 5000);
  if (existingConversation) return existingConversation;

  const lines: string[] = [];
  const userQuestion = cleanText(input.user_question, 1000);
  const aiReply = cleanText(input.ai_reply, 1000);
  const checkedSteps = normalizeCheckedSteps(input.checked_steps);
  const unresolvedReason = cleanText(input.unresolved_reason ?? input.transfer_reason, 500);

  if (userQuestion) lines.push(`用户：${userQuestion}`);
  if (aiReply) lines.push(`AI：${aiReply}`);
  if (checkedSteps.length > 0) {
    lines.push("已排查步骤：");
    checkedSteps.forEach((step, index) => lines.push(`${index + 1}. ${step}`));
  }
  if (unresolvedReason) lines.push(`未解决原因：${unresolvedReason}`);

  return lines.join("\n");
}

export function extractCheckedSteps(row: UnresolvedExportRow): string {
  const conversation = cleanText(row.conversation, 5000);
  if (!conversation) return "";

  try {
    const parsed = JSON.parse(conversation) as { checked_steps?: unknown };
    const steps = normalizeCheckedSteps(parsed.checked_steps);
    if (steps.length > 0) return steps.join("；");
  } catch {
    // 普通文本会走下面的解析逻辑。
  }

  const lines = conversation.split(/\r?\n/);
  const steps: string[] = [];
  let inSteps = false;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      if (inSteps && steps.length > 0) break;
      continue;
    }

    if (/^已排查步骤[：:]/.test(line)) {
      inSteps = true;
      const inline = line.replace(/^已排查步骤[：:]\s*/, "").trim();
      if (inline) steps.push(...normalizeCheckedSteps(inline));
      continue;
    }

    if (inSteps && /^(未解决原因|用户|AI|客服|机器人)[：:]/.test(line)) break;
    if (inSteps) steps.push(...normalizeCheckedSteps(line));
  }

  return steps.join("；");
}

export function toExportRecord(row: UnresolvedExportRow): Record<string, string> {
  return {
    记录ID: cleanText(row.id, 80),
    会话ID: cleanText(row.session_id, 120),
    渠道: cleanText(row.platform_code, 80) || "未知",
    用户原话: cleanText(row.user_question, 1000),
    问题类型: cleanText(row.category, 120) || "未分类",
    AI回复: cleanText(row.ai_reply, 1000),
    AI已排查步骤: extractCheckedSteps(row),
    未解决原因: cleanText(row.transfer_reason, 500),
    状态: cleanText(row.status, 80),
    创建时间: cleanText(row.created_at, 80),
  };
}

export function csvEscape(value: unknown): string {
  const text = cleanText(value, 5000);
  if (/[",\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

export function htmlEscape(value: unknown): string {
  return cleanText(value, 5000)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
