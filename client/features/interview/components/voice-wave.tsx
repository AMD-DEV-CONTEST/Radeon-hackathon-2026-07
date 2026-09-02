"use client";

import { motion } from "framer-motion";

import { cn } from "@/lib/utils";

interface VoiceWaveProps {
  isActive?: boolean;
  bars?: number;
  className?: string;
}

export function VoiceWave({
  isActive = false,
  bars = 28,
  className,
}: VoiceWaveProps) {
  return (
    <div
      className={cn(
        "flex h-16 items-center justify-center gap-1",
        className
      )}
      aria-hidden="true"
    >
      {Array.from({ length: bars }, (_, index) => {
        const mid = bars / 2;
        const distance = Math.abs(index - mid);
        const base = Math.max(0.25, 1 - distance / mid);

        return (
          <motion.span
            key={index}
            className="w-1 rounded-full bg-primary"
            animate={
              isActive
                ? {
                    scaleY: [base * 0.45, base, base * 0.55, base * 0.9],
                    opacity: [0.55, 1, 0.7, 1],
                  }
                : { scaleY: 0.3, opacity: 0.35 }
            }
            transition={
              isActive
                ? {
                    duration: 0.9 + (index % 5) * 0.08,
                    repeat: Number.POSITIVE_INFINITY,
                    ease: "easeInOut",
                    delay: index * 0.02,
                  }
                : { duration: 0.25 }
            }
            style={{ height: 48, originY: 0.5 }}
          />
        );
      })}
    </div>
  );
}
