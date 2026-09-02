"use client";

import { Mic, MicOff } from "lucide-react";

import { cn } from "@/lib/utils";

interface MicrophoneStatusProps {
  isMuted: boolean;
  isSpeaking?: boolean;
  className?: string;
}

export function MicrophoneStatus({
  isMuted,
  isSpeaking = false,
  className,
}: MicrophoneStatusProps) {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-medium",
        isMuted
          ? "border-destructive/40 bg-destructive/10 text-destructive"
          : "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
        className
      )}
      aria-live="polite"
    >
      {isMuted ? (
        <MicOff className="h-3.5 w-3.5" aria-hidden="true" />
      ) : (
        <Mic
          className={cn("h-3.5 w-3.5", isSpeaking && "animate-pulse")}
          aria-hidden="true"
        />
      )}
      {isMuted ? "Microphone Muted" : "Microphone Live"}
    </div>
  );
}
