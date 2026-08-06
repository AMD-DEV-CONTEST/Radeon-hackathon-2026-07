import type { ChatMessage } from "./types";

const FOOD_NAMES: Record<string, string> = {
  "food-tofu": "豆腐",
  "food-chicken-leg": "鸡腿",
  "food-cabbage": "白菜",
  "food-rice-cooked": "熟米饭",
  "food-egg": "鸡蛋",
  "food-shiitake": "香菇",
  "food-tomato": "番茄",
  "food-potato": "土豆",
  "food-spinach": "菠菜",
  "food-carrot": "胡萝卜",
  "food-fish-fillet": "鱼片",
  "food-pork-lean": "瘦猪肉",
  "food-beef": "牛肉",
  "food-peanut": "花生",
  "food-scallion": "葱",
  "food-garlic": "蒜",
  "food-cucumber": "黄瓜",
  "food-millet": "小米"
};

const MEMBER_NAMES: Record<string, string> = {
  "mem-admin": "管理员",
  "mem-father": "父亲",
  "mem-mother": "母亲"
};

const TEMPLATE_NAMES: Record<string, string> = {
  "tpl-cabbage-tofu-braise": "白菜豆腐煲",
  "tpl-tomato-egg": "番茄炒蛋",
  "tpl-steamed-fish": "清蒸鱼片",
  "tpl-potato-chicken": "土豆炖鸡腿",
  "tpl-tomato-beef": "番茄牛肉",
  "tpl-pork-cabbage": "白菜炒瘦肉",
  "tpl-shiitake-egg": "香菇蒸蛋",
  "tpl-cucumber-salad": "凉拌黄瓜",
  "tpl-garlic-spinach": "蒜蓉菠菜",
  "tpl-carrot-stir": "清炒胡萝卜",
  "tpl-leftover-rice": "昨日米饭",
  "tpl-plain-rice": "白米饭",
  "tpl-millet-porridge": "小米粥"
};

export const ROLE_NAMES: Record<string, string> = {
  admin: "家庭管理员",
  father: "父亲",
  mother: "母亲"
};

export const HEALTH_TAG_NAMES: Record<string, string> = {
  weight_management: "体重管理",
  stable_type2_diabetes_demo: "血糖管理",
  hypertension_demo: "血压管理"
};

const MEAL_ROLE_NAMES: Record<string, string> = {
  shared_main: "主菜 / 蛋白质",
  shared_side: "蔬菜 / 配菜",
  staple: "主食 / 碳水"
};

const TOOL_NAMES: Record<string, string> = {
  get_day_context: "读取今日额度与家庭记忆",
  find_dish_candidates: "匹配候选菜品",
  finalize_meal_plan: "确认选菜并生成计划",
  preview_meal_completion: "预览本餐完成后的写入",
  preview_caregiver_task: "预览任务卡与采购清单",
  retrieve_local_knowledge: "检索本地知识库",
  preview_inventory_change: "预览库存入库",
  preview_member_memory_change: "预览家庭资料变更"
};

export const CHAT_ROLE_NAMES: Record<ChatMessage["role"], string> = {
  user: "你",
  assistant: "PrivatePlate",
  system: "系统"
};

export function foodName(foodId: string): string {
  return (
    FOOD_NAMES[foodId] ??
    foodId.replace(/^food-/, "").replaceAll("-", "")
  );
}

export function memberName(
  memberId: string,
  lookup?: Map<string, string> | Record<string, string>
): string {
  if (lookup instanceof Map && lookup.has(memberId)) {
    return lookup.get(memberId)!;
  }
  if (lookup && !(lookup instanceof Map) && lookup[memberId]) {
    return lookup[memberId]!;
  }
  return MEMBER_NAMES[memberId] ?? memberId.replace(/^mem-/, "");
}

export function templateName(templateId: string): string {
  return (
    TEMPLATE_NAMES[templateId] ??
    templateId.replace(/^tpl-/, "").replaceAll("-", " ")
  );
}

export function toolName(tool: string): string {
  return TOOL_NAMES[tool] ?? tool.replaceAll("_", " ");
}

export function confidenceName(confidence: string): string {
  if (confidence === "exact") return "精确";
  if (confidence === "approximate") return "约数";
  if (confidence === "unknown") return "待确认";
  return confidence;
}

export function shoppingStatusName(status: string): string {
  if (status === "needed") return "需采购";
  if (status === "needs_confirmation") return "待确认库存";
  if (status === "not_needed") return "够用";
  return status;
}

export function mealRoleName(role: string): string {
  return MEAL_ROLE_NAMES[role] ?? role;
}

/** Demo-friendly grams: integers, or one decimal only when needed. */
export function formatGrams(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const rounded = Math.round(value);
  if (Math.abs(value - rounded) < 0.05) return `${rounded}`;
  return `${Math.round(value * 10) / 10}`;
}

export function formatKcal(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${Math.round(value)}`;
}

export function formatMg(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${Math.round(value)}`;
}

export function quantityName(quantity: {
  estimateG: number | null;
  minG: number | null;
  maxG: number | null;
  confidence: string;
}): string {
  if (quantity.confidence === "exact" && quantity.estimateG != null) {
    return `${formatGrams(quantity.estimateG)} g`;
  }
  if (
    quantity.confidence === "approximate" &&
    quantity.minG != null &&
    quantity.maxG != null
  ) {
    return `约 ${formatGrams(quantity.minG)}–${formatGrams(quantity.maxG)} g`;
  }
  return "数量待确认";
}

/**
 * Replace internal ids and over-precise numbers so chat is readable in the product UI.
 */
export function humanizeProductText(
  text: string,
  memberLookup?: Map<string, string>
): string {
  let out = text;
  // Chat bubbles are plain text. Models often emit HTML breaks / markdown bold;
  // normalize before id replacement and line-based compacting.
  out = out.replace(/<br\s*\/?>/gi, "\n");
  out = out.replace(/\*\*(.+?)\*\*/g, "$1");
  out = out.replace(/__(.+?)__/g, "$1");
  const members = [
    ...Object.keys(MEMBER_NAMES),
    ...(memberLookup ? [...memberLookup.keys()] : [])
  ];
  for (const id of members) {
    out = out.split(id).join(memberName(id, memberLookup));
  }
  for (const [id, name] of Object.entries(FOOD_NAMES)) {
    out = out.split(id).join(name);
  }
  for (const [id, name] of Object.entries(TEMPLATE_NAMES)) {
    out = out.split(id).join(name);
  }
  // Remaining unknown food-/tpl-/mem- tokens → strip prefix.
  out = out.replace(/\bfood-([a-z0-9-]+)\b/gi, (_, rest: string) =>
    rest.replaceAll("-", "")
  );
  out = out.replace(/\btpl-([a-z0-9-]+)\b/gi, (_, rest: string) =>
    rest.replaceAll("-", " ")
  );
  out = out.replace(/\bmem-([a-z0-9-]+)\b/gi, (_, rest: string) => rest);
  out = out.replace(/\bplan-[a-f0-9-]{8,}\b/gi, "当前计划");
  out = out.replace(/\bbundle-[a-z0-9-]+\b/gi, "推荐方案");
  out = out.replace(/\bpending-[a-f0-9-]{8,}\b/gi, "待确认任务");
  // 123.450 / 65.000 → 123 / 65；保留一位小数当需要
  out = out.replace(/(\d+)\.(\d{2,})/g, (_m, intPart: string, frac: string) => {
    const n = Number(`${intPart}.${frac}`);
    if (!Number.isFinite(n)) return _m;
    const rounded = Math.round(n);
    if (Math.abs(n - rounded) < 0.05) return String(rounded);
    return String(Math.round(n * 10) / 10);
  });
  return out;
}

/**
 * Optional compact view for very long assistant answers.
 * Real Agent dashboard uses compact=false by default.
 */
export function shortenChatAnswer(
  text: string,
  options?: { hasPlan?: boolean; maxLines?: number; maxChars?: number }
): string {
  const maxLines = options?.maxLines ?? 5;
  const maxChars = options?.maxChars ?? 320;
  const lines = text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
  // Drop pure markdown table/debug noise.
  const cleaned = lines.filter(
    (line) =>
      !/^\|/.test(line) &&
      !/^[-*]{3,}$/.test(line) &&
      !/schema_version|toolTrace|effectiveArguments/i.test(line)
  );
  let body = cleaned.slice(0, maxLines).join("\n");
  let truncated = cleaned.length > maxLines;
  if (body.length > maxChars) {
    body = `${body.slice(0, maxChars).trim()}…`;
    truncated = true;
  }
  if (truncated && options?.hasPlan) {
    body = `${body}\n（详情见右侧计划）`;
  }
  return body;
}

export function prepareChatAnswer(
  text: string,
  options?: {
    memberLookup?: Map<string, string>;
    hasPlan?: boolean;
    compact?: boolean;
  }
): string {
  const human = humanizeProductText(text, options?.memberLookup);
  if (options?.compact === false) return human;
  return shortenChatAnswer(human, {
    hasPlan: options?.hasPlan,
    maxLines: 5,
    maxChars: 360
  });
}

/** @deprecated aliases */
export const humanizeDemoText = humanizeProductText;
export const prepareDemoAnswer = prepareChatAnswer;
export const shortenDemoAnswer = shortenChatAnswer;
