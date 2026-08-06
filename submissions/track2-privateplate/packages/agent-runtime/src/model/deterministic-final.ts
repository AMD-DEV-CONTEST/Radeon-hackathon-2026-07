import type { AgentGoal } from "../contracts.js";
import type { ModelVisibleToolResult } from "./provider.js";

type LoopGoal = Exclude<AgentGoal, "no_action" | "unsupported">;

export function renderStructuredInfeasible(input: {
  priorFailureCode: string | null;
  deficits: Array<Record<string, unknown>>;
  recommendedActions: string[];
  failureKind: string | null;
  allowedRelaxations: Array<{ constraintId: string; userFacingQuestion: string }>;
}): string {
  const deficitLines = input.deficits.slice(0, 6).map((deficit) => {
    const nutrient = stringValue(deficit.nutrient) || "营养";
    const member = stringValue(deficit.memberId);
    const scope = member ? `${member}/` : "";
    if (typeof deficit.deficit === "number" && deficit.deficit > 0) {
      return `- ${scope}${nutrient} 不足 ${deficit.deficit}`;
    }
    if (typeof deficit.excess === "number" && deficit.excess > 0) {
      return `- ${scope}${nutrient} 超出 ${deficit.excess}`;
    }
    return `- ${scope}${nutrient} 未通过`;
  });
  const actions =
    input.recommendedActions.length > 0
      ? input.recommendedActions.join("、")
      : "调整软偏好、份量或菜品组合";
  const relaxations = input.allowedRelaxations
    .map((item) => item.userFacingQuestion)
    .filter(Boolean);
  const lines = [
    "当前选择在硬约束下无法形成可行餐食（NO_FEASIBLE_PLAN）。",
    input.priorFailureCode
      ? `最近一次 Domain 拒绝：${input.priorFailureCode}${input.failureKind ? ` / ${input.failureKind}` : ""}。`
      : null,
    deficitLines.length > 0 ? `结构化缺口：\n${deficitLines.join("\n")}` : null,
    `建议下一步：${actions}。`,
    relaxations.length > 0 ? relaxations.join(" ") : "请说明愿意调整的软偏好后再试；硬约束和明确拒绝项均未放宽。"
  ];
  return lines.filter(Boolean).join("\n");
}

export function renderDeterministicFinal(input: {
  goal: LoopGoal;
  toolResults: ModelVisibleToolResult[];
  blockedReason?: string;
}): string | null {
  if (input.blockedReason === "plan_infeasible") {
    return "当前硬约束和明确拒绝下没有可行计划（NO_FEASIBLE_PLAN）。请说明愿意调整的软偏好后再试；硬约束未被放宽。";
  }
  if (input.blockedReason === "approved_evidence_missing") {
    return "当前没有检索到足够的审核依据，本轮已停止，不会编造解释。";
  }

  if (input.blockedReason) {
    const failedResult = [...input.toolResults]
      .reverse()
      .find((item) => !item.ok && item.data);
    const safeMessage = stringValue(failedResult?.data?.message);
    if (safeMessage) return safeMessage;
  }

  const result = [...input.toolResults]
    .reverse()
    .find((item) => item.ok && item.goal === input.goal && item.data);
  if (!result?.data) return null;

  switch (result.tool) {
    case "get_day_context":
      return renderContext(result.data);
    case "get_inventory":
      return renderInventory(result.data);
    case "finalize_meal_plan":
      return renderPlan(result.data, "家庭餐已生成");
    case "find_dish_candidates":
      return "已获取候选菜品事实，请基于候选完成选择。";
    case "preview_meal_completion":
      return "已预览本餐完成后的摄入与库存变化；请在界面确认后才会写入。";
    case "preview_caregiver_task":
      return renderPreview(result.data);
    case "retrieve_local_knowledge":
      return renderRag(result.data);
    case "preview_inventory_change":
      return "已预览库存入库影响；请在界面点「确认入库」后才会修改 SQLite。";
    case "preview_member_memory_change":
      return "已预览家庭资料变更；请在界面点「确认保存家庭资料」后才会写入。";
    default:
      return null;
  }
}

function renderRag(data: Record<string, unknown>): string {
  const hits = records(data.hits);
  if (hits.length === 0) {
    return "本地知识库没有检索到足够相关的内容，本轮不会编造来源。";
  }
  return hits
    .map((hit) => {
      const title = stringValue(hit.title);
      const content = stringValue(hit.content);
      const source = stringValue(hit.sourcePath);
      const score =
        typeof hit.score === "number" ? hit.score.toFixed(3) : "";
      return `${title}（${source}${score ? ` score=${score}` : ""}）：${content}`;
    })
    .join("\n");
}

function renderContext(data: Record<string, unknown>): string {
  const members = records(data.members)
    .map((member) => stringValue(member.displayName))
    .filter(Boolean);
  const inventory = records(data.inventory)
    .map((item) => stringValue(item.quantity))
    .filter(Boolean);
  const lines = ["家庭用餐上下文已读取。"];
  if (members.length > 0) lines.push(`成员：${members.join("、")}。`);
  if (inventory.length > 0) lines.push(`库存：${inventory.join("；")}。`);
  return lines.join("\n");
}

function renderInventory(data: Record<string, unknown>): string {
  const inventory = records(data.inventory);
  if (inventory.length === 0) return "当前库存为空。";
  const lines = inventory.slice(0, 12).map((item) => {
    const name = stringValue(item.rawName) || stringValue(item.foodId) || "食材";
    const quantity = record(item.quantity);
    const grams =
      typeof quantity.estimateG === "number" ? `${quantity.estimateG}g` : "";
    return grams ? `${name} ${grams}` : name;
  });
  return `当前库存：${lines.join("、")}。`;
}

function renderPlan(data: Record<string, unknown>, heading: string): string {
  const plan = record(data.plan);
  const menu = records(plan.menu)
    .map((item) => stringValue(item.name))
    .filter(Boolean);
  if (menu.length === 0) return `${heading}，但当前结果没有可展示的菜品。`;
  return `${heading}：${menu.join("、")}。`;
}

function renderGuidance(data: Record<string, unknown>): string {
  const cards = records(data.cards);
  if (cards.length === 0) {
    return "当前没有检索到足够的审核依据，本轮已停止，不会编造解释。";
  }
  return cards
    .map((card) => {
      const title = stringValue(card.title);
      const content = stringValue(card.relevantContent);
      const sourceId = stringValue(card.sourceId);
      return `${title}：${content}（依据：${sourceId}）`;
    })
    .join("\n");
}

function renderPreview(data: Record<string, unknown>): string {
  const taskCard = record(data.taskCard);
  const recipient = stringValue(taskCard.recipientLabel);
  const menu = records(taskCard.menu)
    .map((item) => stringValue(item.displayName))
    .filter(Boolean);
  const summary = menu.length > 0 ? `，菜单为${menu.join("、")}` : "";
  return `给${recipient || "执行者"}的任务卡预览已生成${summary}。尚未发送，仍需在界面确认。`;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}
