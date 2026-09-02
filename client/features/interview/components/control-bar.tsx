"use client";

import { motion } from "framer-motion";
import {
  Camera,
  CameraOff,
  LogOut,
  Mic,
  MicOff,
  MonitorUp,
  Settings,
  SkipForward,
  Square,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { NetworkStatus } from "@/features/interview/components/network-status";
import { cn } from "@/lib/utils";

interface ControlBarProps {
  sessionId: string;
  isLive: boolean;
  isMuted: boolean;
  isCameraOn: boolean;
  isScreenShareEnabled: boolean;
  latencyMs: number;
  isConnected: boolean;
  isEnding?: boolean;
  onToggleMute: () => void;
  onToggleCamera: () => void;
  onSkipQuestion: () => void;
  onStopRecording: () => void;
  onEndInterview: () => void;
}

export function ControlBar({
  sessionId,
  isLive,
  isMuted,
  isCameraOn,
  isScreenShareEnabled,
  latencyMs,
  isConnected,
  isEnding = false,
  onToggleMute,
  onToggleCamera,
  onSkipQuestion,
  onStopRecording,
  onEndInterview,
}: ControlBarProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="sticky bottom-0 z-20 border-t border-border/70 bg-[#0b0b12]/95 px-3 py-3 backdrop-blur-xl sm:px-4"
      role="toolbar"
      aria-label="Interview session controls"
    >
      <div className="mx-auto flex max-w-7xl flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3 text-sm">
          <span
            className={cn(
              "inline-flex items-center gap-2 font-semibold",
              isLive ? "text-white" : "text-muted-foreground"
            )}
          >
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                isLive ? "animate-pulse bg-destructive" : "bg-muted-foreground"
              )}
            />
            {isLive ? "Session Live" : "Session Idle"}
          </span>
          <span className="font-mono text-xs text-muted-foreground">
            {sessionId}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={isMuted ? "Unmute microphone" : "Mute microphone"}
            aria-pressed={isMuted}
            onClick={onToggleMute}
          >
            {isMuted ? (
              <MicOff className="h-4 w-4" />
            ) : (
              <Mic className="h-4 w-4" />
            )}
          </Button>

          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={isCameraOn ? "Turn camera off" : "Turn camera on"}
            aria-pressed={!isCameraOn}
            onClick={onToggleCamera}
          >
            {isCameraOn ? (
              <Camera className="h-4 w-4" />
            ) : (
              <CameraOff className="h-4 w-4" />
            )}
          </Button>

          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Screen share unavailable"
            disabled
            title="Screen share coming soon"
          >
            <MonitorUp
              className={cn(
                "h-4 w-4",
                !isScreenShareEnabled && "opacity-60"
              )}
            />
          </Button>

          <Button
            type="button"
            variant="outline"
            className="h-9 border-destructive/50 text-destructive hover:bg-destructive/10"
            onClick={onStopRecording}
          >
            <Square className="h-3.5 w-3.5 fill-current" aria-hidden="true" />
            Stop Recording
          </Button>

          <Button
            type="button"
            variant="outline"
            className="h-9"
            onClick={onSkipQuestion}
          >
            <SkipForward className="h-4 w-4" aria-hidden="true" />
            Skip Question
          </Button>

          <motion.div whileHover={{ scale: isEnding ? 1 : 1.01 }}>
            <Button
              type="button"
              className="h-9 bg-destructive text-white hover:bg-destructive/90"
              disabled={isEnding}
              aria-busy={isEnding}
              onClick={onEndInterview}
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
              End Interview
            </Button>
          </motion.div>
        </div>

        <div className="flex items-center gap-3">
          <NetworkStatus latencyMs={latencyMs} isConnected={isConnected} />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Session settings"
          >
            <Settings className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </motion.div>
  );
}
