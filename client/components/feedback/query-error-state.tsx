"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface QueryErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  className?: string;
}

export function QueryErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  className,
}: QueryErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center rounded-2xl border border-destructive/30 bg-destructive/5 px-6 py-12 text-center",
        className
      )}
    >
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/15 text-destructive">
        <AlertTriangle className="h-5 w-5" aria-hidden="true" />
      </div>
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">{message}</p>
      {onRetry ? (
        <Button
          type="button"
          variant="outline"
          className="mt-5 h-10"
          onClick={onRetry}
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          Retry
        </Button>
      ) : null}
    </div>
  );
}
