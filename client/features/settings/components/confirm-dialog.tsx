"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, X } from "lucide-react";
import { useEffect, useId, useRef } from "react";

import { Button } from "@/components/ui/button";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  destructive = false,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    confirmRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onCancel();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel, open]);

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <button
            type="button"
            className="absolute inset-0 bg-black/70"
            aria-label="Close confirmation dialog"
            onClick={onCancel}
          />
          <motion.div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={descriptionId}
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            className="relative z-10 w-full max-w-md rounded-2xl border border-white/10 bg-[#12121a] p-5 shadow-2xl"
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-destructive/15 text-destructive">
                  <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                </div>
                <div>
                  <h2 id={titleId} className="text-lg font-semibold text-white">
                    {title}
                  </h2>
                  <p
                    id={descriptionId}
                    className="mt-1 text-sm text-muted-foreground"
                  >
                    {description}
                  </p>
                </div>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Close"
                onClick={onCancel}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>

            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={onCancel}
              >
                {cancelLabel}
              </Button>
              <Button
                ref={confirmRef}
                type="button"
                disabled={busy}
                className={
                  destructive
                    ? "bg-destructive text-white hover:bg-destructive/90"
                    : "glow-purple"
                }
                onClick={onConfirm}
              >
                {busy ? "Working..." : confirmLabel}
              </Button>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
