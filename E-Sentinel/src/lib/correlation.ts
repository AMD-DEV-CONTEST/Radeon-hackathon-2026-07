import { nanoid } from "nanoid";

/** 在 API 入口生成唯一链路追踪 ID，贯穿 Redis → LLM → Supabase → Feishu 全链路 */
export function createCorrelationId(prefix: string = "qa"): string {
  return `${prefix}_${nanoid(12)}`;
}
