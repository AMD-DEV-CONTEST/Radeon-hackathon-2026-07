"use client";

import { type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { AlertTriangle, Inbox, ShieldCheck } from "lucide-react";

interface PanelProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  empty?: boolean;
  emptyIcon?: ReactNode;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: { label: string; onClick: () => void };
  children?: ReactNode;
}

function SkeletonRow() {
  return <div className="h-10 bg-muted rounded-lg animate-pulse" />;
}

export default function Panel({
  title,
  subtitle,
  actions,
  loading = false,
  error = null,
  onRetry,
  empty = false,
  emptyIcon,
  emptyTitle = "暂无数据",
  emptyDescription,
  emptyAction,
  children,
}: PanelProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background">
      {/* Header */}
      <header className="sticky top-0 z-10 border-b border-border/60 bg-background/75 backdrop-blur-xl px-4 sm:px-6 py-3.5 sm:py-4">
        <div className="flex w-full flex-col sm:flex-row sm:items-center sm:justify-between gap-2 max-w-7xl mx-auto">
          <div className="flex items-center gap-2.5">
            <div className="grid place-items-center w-7 h-7 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 shadow-sm shadow-brand-700/25 ring-1 ring-white/20 shrink-0">
              <ShieldCheck className="w-4 h-4 text-white" strokeWidth={2.3} />
            </div>
            <div>
              <h1 className="text-[18px] font-bold tracking-[-0.02em] text-foreground">{title}</h1>
              {subtitle && <p className="text-[12.5px] text-muted-foreground mt-0.5 tracking-tight">{subtitle}</p>}
            </div>
          </div>
          {actions && <div className="flex flex-wrap items-center justify-start sm:justify-end gap-2">{actions}</div>}
        </div>
      </header>

      <div className="w-full p-4 sm:p-6 max-w-7xl mx-auto">
        {/* Error banner */}
        {error && (
          <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" strokeWidth={2} />
              <span>{error}</span>
            </div>
            {onRetry && (
              <button
                type="button"
                aria-label="重试加载"
                className="text-destructive/70 hover:text-destructive text-xs font-semibold shrink-0 ml-3 px-2 py-1 rounded-md hover:bg-destructive/10 transition-colors"
                onClick={onRetry}
              >
                重试
              </button>
            )}
          </div>
        )}

        {/* Loading skeleton */}
        {loading && !error && (
          <div className="space-y-3" aria-busy="true" aria-live="polite">
            {[1, 2, 3, 4].map((i) => (
              <SkeletonRow key={i} />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && empty && (
          <div className="bg-card rounded-xl border border-border/60 py-16 px-6 text-center">
            {emptyIcon ? (
              <div className="mb-4 flex justify-center text-muted-foreground/30 [&>svg]:w-11 [&>svg]:h-11">
                {emptyIcon}
              </div>
            ) : (
              <div className="mb-4 flex justify-center text-muted-foreground/30">
                <Inbox className="w-11 h-11" strokeWidth={1.2} />
              </div>
            )}
            <p className="text-sm font-semibold text-foreground mb-1">{emptyTitle}</p>
            {emptyDescription && (
              <p className="text-xs text-muted-foreground mb-5 max-w-xs mx-auto">{emptyDescription}</p>
            )}
            <div className="flex items-center justify-center gap-2">
              {emptyAction && (
                <Button size="sm" onClick={emptyAction.onClick}>
                  {emptyAction.label}
                </Button>
              )}
            </div>
          </div>
        )}

        {/*
         * Keep panel children mounted while the empty state is visible. A
         * number of panels define their create/import dialogs inside
         * `children`; unmounting them here made empty-state actions update
         * state without mounting any dialog, which looked like a dead click.
         * Portaled dialogs remain interactive, while the panel body stays
         * hidden until the empty state is cleared.
         */}
        {!loading && !error && children && (
          <div className={empty ? "panel-empty-content" : undefined}>
            {children}
          </div>
        )}
      </div>
    </div>
  );
}
