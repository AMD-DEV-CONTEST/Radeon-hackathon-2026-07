"use client";

import { motion } from "framer-motion";
import { Brain } from "lucide-react";

import { cn } from "@/lib/utils";

interface AiThinkingProps {
  isThinking: boolean;
  className?: string;
}

export function AiThinking({ isThinking, className }: AiThinkingProps) {
  if (!isThinking) {
    return null;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary",
        className
      )}
      role="status"
      aria-live="polite"
    >
      <Brain className="h-3.5 w-3.5 animate-pulse" aria-hidden="true" />
      <span>Vox-1 is thinking</span>
      <span className="inline-flex gap-0.5" aria-hidden="true">
        {[0, 1, 2].map((dot) => (
          <motion.span
            key={dot}
            className="h-1 w-1 rounded-full bg-primary"
            animate={{ opacity: [0.3, 1, 0.3], y: [0, -2, 0] }}
            transition={{
              duration: 0.9,
              repeat: Number.POSITIVE_INFINITY,
              delay: dot * 0.15,
            }}
          />
        ))}
      </span>
    </motion.div>
  );
}
