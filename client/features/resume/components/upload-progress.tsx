"use client";

import { motion } from "framer-motion";
import { AlertCircle, CheckCircle2, Loader2, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { UploadProgressState } from "@/features/resume/types/resume.types";
import { cn } from "@/lib/utils";

interface UploadProgressProps {
  state: UploadProgressState;
  className?: string;
  onRetry?: () => void;
  isRetrying?: boolean;
}

export function UploadProgress({
  state,
  className,
  onRetry,
  isRetrying = false,
}: UploadProgressProps) {
  if (state.status === "idle") {
    return null;
  }

  const isError = state.status === "error";
  const isSuccess = state.status === "success";
  const isUploading = state.status === "uploading";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={cn(
        "rounded-xl border px-4 py-3",
        isError && "border-destructive/40 bg-destructive/10",
        isSuccess && "border-success/40 bg-success/10",
        isUploading && "border-primary/30 bg-primary/5",
        className
      )}
      role="status"
      aria-live="polite"
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm">
          {isUploading ? (
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
          ) : null}
          {isSuccess ? (
            <CheckCircle2 className="h-4 w-4 text-success" />
          ) : null}
          {isError ? (
            <AlertCircle className="h-4 w-4 text-destructive" />
          ) : null}
          <span
            className={cn(
              "font-medium",
              isUploading && "text-white",
              isSuccess && "text-success",
              isError && "text-destructive"
            )}
          >
            {isUploading ? "Uploading resume..." : null}
            {isSuccess ? "Resume uploaded successfully" : null}
            {isError ? "Upload failed" : null}
          </span>
        </div>
        {isUploading || isSuccess ? (
          <span className="text-xs font-semibold text-muted-foreground">
            {state.progress}%
          </span>
        ) : null}
      </div>

      {(isUploading || isSuccess) && (
        <Progress
          value={state.progress}
          className="h-1.5"
          indicatorClassName={isSuccess ? "bg-success" : "bg-primary"}
        />
      )}

      {isError && state.errorMessage ? (
        <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-destructive">{state.errorMessage}</p>
          {onRetry ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 shrink-0"
              disabled={isRetrying}
              aria-busy={isRetrying}
              onClick={onRetry}
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              Retry Upload
            </Button>
          ) : null}
        </div>
      ) : null}
    </motion.div>
  );
}
