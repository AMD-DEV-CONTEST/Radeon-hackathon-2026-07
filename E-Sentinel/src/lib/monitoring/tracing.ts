/**
 * 基础 Trace 上下文工具 (QAE-016 最小切片)
 * 
 * 目标：让已有的 traceparent 能被业务代码方便提取和关联，
 * 为后续引入完整 OpenTelemetry SDK 做准备。
 * 
 * 当前不引入 @opentelemetry 依赖，仅封装 W3C traceparent 处理和上下文提取。
 */

export interface TraceContext {
  /** 原始 W3C traceparent 字符串 */
  traceparent: string | null;
  /** trace-id (32 hex chars) */
  traceId: string | null;
  /** parent-id / span-id (16 hex chars) */
  spanId: string | null;
}

const TRACEPARENT_PATTERN = /^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$/i;

/**
 * 解析 W3C traceparent。
 * 与 evidence-event.ts 中的校验保持一致。
 */
export function parseTraceparent(raw: string | null | undefined): TraceContext {
  if (!raw || typeof raw !== "string") {
    return { traceparent: null, traceId: null, spanId: null };
  }
  const match = TRACEPARENT_PATTERN.exec(raw.trim());
  if (!match) {
    // 非法格式也保留原始值，便于上游日志记录
    return { traceparent: raw, traceId: null, spanId: null };
  }
  return {
    traceparent: raw,
    traceId: match[1],
    spanId: match[2],
  };
}

/**
 * 从 Request Headers 安全提取 traceparent。
 */
export function getTraceparentFromRequest(request: Request): string | null {
  return request.headers.get("traceparent");
}

/**
 * 确保 body 中存在 traceparent（优先使用已有，缺失时从请求头注入）。
 * 直接修改传入的 body（与现有 route 行为一致）。
 */
export function ensureTraceparent(
  body: Record<string, unknown>,
  request: Request
): string | null {
  if (!body.traceparent) {
    const fromHeader = getTraceparentFromRequest(request);
    if (fromHeader) {
      body.traceparent = fromHeader;
    }
  }
  const value = body.traceparent;
  return typeof value === "string" ? value : null;
}

/**
 * 从已验证的事件中提取 TraceContext（供诊断、评估、指标等业务模块使用）。
 */
export function getTraceContextFromEvent(event: { traceparent?: string | null }): TraceContext {
  return parseTraceparent(event.traceparent ?? null);
}
