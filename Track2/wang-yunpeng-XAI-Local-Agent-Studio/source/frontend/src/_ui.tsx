/**
 * XAI 通用 UI 组件库
 * 
 * 统一所有页面的加载/空/错误/确认态，避免每个页面手写 Tailwind。
 * 设计语言对齐 liquid-glass.css 的 CSS 变量和 Tailwind v4 的 .dark 变体。
 * 
 * 导出：
 *   EmptyState     — 空页面/首次引导
 *   ErrorBanner    — 带重试的错误提示
 *   Skeleton       — 骨架屏加载占位
 *   ConfirmDialog  — 模态确认弹窗
 */

import { type ReactNode } from "react";
import { AlertCircle, RefreshCw, type LucideIcon } from "lucide-react";

/* ================================================================
   EmptyState — 空状态引导
   用法：<EmptyState icon={Database} title="还没有知识库" 
           description="导入文档或网页开始构建你的知识库" 
           actionLabel="导入文档" onAction={() => ...} />
================================================================ */
interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({ icon: Icon, title, description, actionLabel, onAction }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      <div className="w-16 h-16 rounded-2xl bg-white/[0.04] dark:bg-white/[0.04] 
                      border border-white/[0.06] flex items-center justify-center mb-5">
        <Icon className="w-8 h-8 text-zinc-400 dark:text-zinc-500" strokeWidth={1.5} />
      </div>
      <h3 className="text-lg font-medium text-zinc-200 dark:text-zinc-200 mb-2">{title}</h3>
      {description && (
        <p className="text-sm text-zinc-500 dark:text-zinc-500 max-w-sm leading-relaxed mb-6">
          {description}
        </p>
      )}
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="px-5 py-2.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.10] 
                     border border-white/[0.08] text-sm font-medium text-zinc-300 
                     transition-all duration-150 active:scale-[0.97]"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}

/* ================================================================
   ErrorBanner — 带重试的错误提示条
   用法：<ErrorBanner message="加载失败" onRetry={() => load()} />
================================================================ */
interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorBanner({ message, onRetry }: ErrorBannerProps) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 mx-3 mt-3 rounded-xl
                    bg-red-500/[0.06] border border-red-500/[0.12]
                    text-sm text-red-400">
      <AlertCircle className="w-4 h-4 shrink-0" strokeWidth={1.5} />
      <span className="flex-1">{message}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                     bg-red-500/[0.08] hover:bg-red-500/[0.14]
                     text-xs font-medium transition-colors duration-150"
        >
          <RefreshCw className="w-3 h-3" />
          重试
        </button>
      )}
    </div>
  );
}

/* ================================================================
   Skeleton — 骨架屏加载占位
   用法：<Skeleton lines={5} />
================================================================ */
interface SkeletonProps {
  lines?: number;
  className?: string;
}

export function Skeleton({ lines = 3, className = "" }: SkeletonProps) {
  return (
    <div className={`space-y-3 px-4 py-6 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-4 rounded-lg bg-white/[0.04] animate-pulse"
          style={{
            width: i === lines - 1 ? "60%" : i === 0 ? "90%" : `${75 + Math.random() * 20}%`,
          }}
        />
      ))}
    </div>
  );
}

/* ================================================================
   ConfirmDialog — 模态确认弹窗
   用法：<ConfirmDialog open={true} title="删除确认" message="此操作不可撤销"
           onConfirm={() => del()} onCancel={() => setOpen(false)} />
================================================================ */
interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open, title, message, confirmLabel = "确认", cancelLabel = "取消",
  danger = false, onConfirm, onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* 遮罩 */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onCancel} />
      {/* 弹窗 */}
      <div className="relative z-10 mx-4 w-full max-w-sm rounded-2xl
                      bg-[var(--color-bg-card)] border border-[var(--color-border)]
                      shadow-[var(--shadow-lg)] p-6">
        <h3 className="text-base font-medium text-[var(--color-text)] mb-2">{title}</h3>
        <p className="text-sm text-[var(--color-text-muted)] leading-relaxed mb-6">{message}</p>
        <div className="flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 rounded-xl text-sm font-medium
                       bg-white/[0.04] hover:bg-white/[0.08]
                       text-[var(--color-text-muted)] transition-colors duration-150"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            className={`px-4 py-2 rounded-xl text-sm font-medium transition-colors duration-150
              ${danger
                ? "bg-red-500/15 hover:bg-red-500/25 text-red-400"
                : "bg-blue-500/15 hover:bg-blue-500/25 text-blue-400"
              }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
