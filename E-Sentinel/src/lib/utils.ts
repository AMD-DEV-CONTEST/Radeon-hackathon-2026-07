import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * 统一百分比格式化 — 接收 0–1 原始比率，输出 1 位小数百分比。
 * 用法：formatPercent(0.8167) → "81.7%"
 * 空值 / NaN / 负值 / >1 异常 → "—"
 */
export function formatPercent(value: number | string | null | undefined): string {
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (num == null || isNaN(num) || num < 0 || num > 1) return "—";
  return `${(num * 100).toFixed(1)}%`;
}

/** 紧凑百分比（整数，KPI 用）：0.8567 → "86%" */
export function formatCompactPercent(value: number | string | null | undefined): string {
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (num == null || isNaN(num) || num < 0 || num > 1) return "—";
  return `${Math.round(num * 100)}%`;
}

/** 评分格式化：formatRating(3.5, 5) → "3.5 / 5" */
export function formatRating(value: number | null | undefined, max: number): string {
  if (value == null || isNaN(value)) return `— / ${max}`;
  return `${value.toFixed(1)} / ${max}`;
}

/** 统一日期时间格式：ISO → "2026-07-30 13:37" */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 金额格式化：1234.5 → "¥1,234.50" */
export function formatCurrency(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return "—";
  return `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** ID 短格式：UUID → 前4后4 "abcd…efgh"，非 UUID 保留原值 */
export function formatShortId(id: string | null | undefined): string {
  if (!id) return "—";
  if (id.length > 16 && id.includes("-")) {
    return `${id.slice(0, 4)}…${id.slice(-4)}`;
  }
  if (id.length > 10) return `${id.slice(0, 6)}…`;
  return id;
}

/** 安全小数格式化（避免浮点尾数）：formatDecimal(0.05, 1) → "0.1" */
export function formatDecimal(value: number | null | undefined, decimals = 1): string {
  if (value == null || isNaN(value)) return "—";
  return value.toFixed(decimals);
}
