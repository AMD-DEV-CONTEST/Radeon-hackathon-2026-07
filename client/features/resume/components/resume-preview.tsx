"use client";

import { motion } from "framer-motion";
import { FileText, RefreshCw, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ResumePreviewProps {
  file: File;
  disabled?: boolean;
  onRemove: () => void;
  onReplace: () => void;
  className?: string;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ResumePreview({
  file,
  disabled = false,
  onRemove,
  onReplace,
  className,
}: ResumePreviewProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={cn(
        "flex flex-col gap-3 rounded-xl border border-border/80 bg-[#12121a] p-4 sm:flex-row sm:items-center sm:justify-between",
        className
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/15 text-primary">
          <FileText className="h-5 w-5" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-white" title={file.name}>
            {file.name}
          </p>
          <p className="text-xs text-muted-foreground">
            {formatFileSize(file.size)} · Selected resume
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9"
          disabled={disabled}
          onClick={onReplace}
          aria-label="Replace selected resume file"
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          Replace
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-9 text-destructive hover:text-destructive"
          disabled={disabled}
          onClick={onRemove}
          aria-label="Remove selected resume file"
        >
          <Trash2 className="h-4 w-4" aria-hidden="true" />
          Remove
        </Button>
      </div>
    </motion.div>
  );
}
