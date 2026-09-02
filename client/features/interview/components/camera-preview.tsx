"use client";

import { motion } from "framer-motion";
import { Camera, CameraOff } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface CameraPreviewProps {
  isOn: boolean;
  candidateInitials: string;
  className?: string;
}

export function CameraPreview({
  isOn,
  candidateInitials,
  className,
}: CameraPreviewProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={className}
    >
      <Card className="overflow-hidden rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0">
        <CardContent className="p-0">
          <div
            className={cn(
              "relative flex aspect-video items-center justify-center",
              isOn
                ? "bg-[radial-gradient(circle_at_30%_30%,rgba(139,92,246,0.25),transparent_45%),linear-gradient(160deg,#1a1030,#0b0b12)]"
                : "bg-[#0b0b12]"
            )}
            role="img"
            aria-label={
              isOn ? "Candidate camera preview placeholder" : "Camera is off"
            }
          >
            {isOn ? (
              <div className="flex h-20 w-20 items-center justify-center rounded-full border border-primary/40 bg-primary/20 text-xl font-bold text-primary">
                {candidateInitials}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 text-muted-foreground">
                <CameraOff className="h-8 w-8" aria-hidden="true" />
                <span className="text-sm">Camera Off</span>
              </div>
            )}

            <div className="absolute top-3 left-3 inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-black/40 px-2.5 py-1 text-[11px] text-white backdrop-blur">
              <Camera className="h-3.5 w-3.5" aria-hidden="true" />
              {isOn ? "Camera Preview" : "Camera Disabled"}
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
