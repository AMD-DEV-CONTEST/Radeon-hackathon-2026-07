import type { ModelVisibleToolResult } from "./provider.js";

const TERMINAL_TOOLS = new Set([
  "finalize_meal_plan",
  "preview_meal_completion",
  "preview_caregiver_task",
  "preview_inventory_change",
  "preview_member_memory_change"
]);

export function isTrustedPresenterTool(tool: string): boolean {
  return TERMINAL_TOOLS.has(tool);
}

export function renderTrustedPresenter(
  results: ModelVisibleToolResult[]
): string | null {
  const result = [...results]
    .reverse()
    .find((item) => item.ok && item.data && isTrustedPresenterTool(item.tool));
  if (!result?.data) {
    return null;
  }

  switch (result.tool) {
    case "finalize_meal_plan":
      return renderMealPlan(result.data);
    case "preview_meal_completion":
      return "已预览按当前计划完成后的摄入与库存变化。尚未写入，仍需通过界面确认。";
    case "preview_caregiver_task":
      return renderCaregiverPreview(
        result.data,
        [...results]
          .reverse()
          .find(
            (item) =>
              item.ok &&
              item.tool === "retrieve_local_knowledge" &&
              item.data
          )
      );
    case "preview_inventory_change":
      return renderInventoryPreview(result.data);
    case "preview_member_memory_change":
      return "家庭资料变更已预览。确认保存前不会写入家庭记忆。";
  }
  return null;
}

function renderMealPlan(data: Record<string, unknown>): string | null {
  const plan = record(data.plan);
  const menu = records(plan.menu)
    .map((item) => text(item.name) || text(item.displayName))
    .filter(Boolean);
  if (menu.length === 0) return null;

  const lines = [`餐食计划已生成：${menu.join("、")}。`];
  const reason = userFacingReason(data.selectionReason);
  if (reason) lines.push(`选择理由：${reason}。`);
  lines.push("份量、营养和采购缺口已核对。\n规划阶段库存保持不变。");
  return lines.join("\n");
}

function renderCaregiverPreview(
  data: Record<string, unknown>,
  retrieval: ModelVisibleToolResult | undefined
): string | null {
  const card = record(data.taskCard);
  const recipient = text(card.recipientLabel);
  const menu = records(card.menu)
    .map((item) => text(item.displayName) || text(item.name))
    .filter(Boolean);
  if (!recipient || menu.length === 0) return null;

  const shoppingItems = records(card.shoppingItems);
  const shopping = shoppingItems.length > 0
    ? "采购缺口已附在任务卡中。"
    : "当前没有需要新增采购的缺口。";
  const rules = retrieval ? renderRetrievedRuleTitles(retrieval.data) : null;
  const ruleLine = rules ? `已查阅本地规则：${rules}。\n` : "";
  return `${ruleLine}给${recipient}的任务卡预览已生成，菜单为${menu.join("、")}。${shopping}尚未发送，仍需在界面确认。`;
}

function renderRetrievedRuleTitles(
  data: Record<string, unknown> | null
): string | null {
  const titles = records(data?.hits)
    .map((hit) => text(hit.title))
    .filter(Boolean)
    .slice(0, 3);
  return titles.length > 0 ? titles.join("、") : null;
}

function userFacingReason(value: unknown): string | null {
  const reason = text(value).replace(/\s+/gu, " ");
  if (
    !reason ||
    reason.length > 120 ||
    !/[\u3400-\u9fff]/u.test(reason) ||
    /…$/u.test(reason)
  ) {
    return null;
  }
  const normalized = reason.replace(/[。．.!！?？；;:：,，、…]+$/gu, "").trim();
  return normalized || null;
}

function renderInventoryPreview(data: Record<string, unknown>): string {
  const preview = record(data.preview);
  const foodName = text(preview.foodName);
  return `${foodName ? `${foodName}的` : "库存"}入库变化已预览。确认入库前不会修改库存。`;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
