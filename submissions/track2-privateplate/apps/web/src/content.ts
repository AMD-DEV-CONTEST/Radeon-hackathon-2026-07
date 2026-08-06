/**
 * UI shortcuts are ordinary user text only — same Agent.handleUserMessage path
 * as free typing. They are not a separate business engine.
 */
export const QUICK_PROMPTS = [
  {
    label: "规划所选成员午餐",
    prompt:
      "请为当前选中的用餐成员安排一顿午餐，豆腐今天最好吃掉，但我不想再吃鸡腿了。"
  },
  {
    label: "替换蒸蛋",
    prompt: "蒸蛋今天也不想吃，换一道，其他都保留。"
  },
  {
    label: "发给保姆",
    prompt: "发给保姆"
  },
  { label: "查看家庭信息", prompt: "查看家庭库存和成员" }
] as const;

/** Placeholder while a turn is in flight — must stay meal-agnostic. */
export const ASSISTANT_PENDING_TEXT = "稍等，我先看看家里的情况…";

const WEEKDAY_LABELS = [
  "周日",
  "周一",
  "周二",
  "周三",
  "周四",
  "周五",
  "周六"
] as const;

/**
 * Display-only local clock for the chat hero.
 * Agent mealType still comes from the user utterance / tool args, not this hint.
 */
export function localMealHero(now = new Date()): {
  kicker: string;
  headline: string;
  mealLabel: "午餐" | "晚餐";
} {
  const hour = now.getHours();
  const mealLabel: "午餐" | "晚餐" = hour < 15 ? "午餐" : "晚餐";
  const hh = String(hour).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  return {
    kicker: `${WEEKDAY_LABELS[now.getDay()]} · ${hh}:${mm}  ·  ${mealLabel}`,
    headline:
      mealLabel === "午餐" ? "午饭吃什么，交给我。" : "今晚吃什么，交给我。",
    mealLabel
  };
}
