"use client";

import { motion } from "framer-motion";
import { Flame } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { AiThinking } from "@/features/interview/components/ai-thinking";
import { InterviewHeader } from "@/features/interview/components/interview-header";
import { MicrophoneStatus } from "@/features/interview/components/microphone-status";
import { VoiceWave } from "@/features/interview/components/voice-wave";
import type { InterviewQuestion } from "@/features/interview/types/interview.types";

interface QuestionCardProps {
  question: InterviewQuestion;
  isMuted: boolean;
  isCandidateSpeaking: boolean;
  isAiThinking: boolean;
}

export function QuestionCard({
  question,
  isMuted,
  isCandidateSpeaking,
  isAiThinking,
}: QuestionCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/85 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-5 p-5 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <InterviewHeader question={question} />
            <Badge
              variant="outline"
              className="border-destructive/40 bg-destructive/10 text-destructive"
            >
              <Flame className="h-3.5 w-3.5" aria-hidden="true" />
              {question.difficulty === "extreme" || question.difficulty === "hard"
                ? "High"
                : question.difficulty}
            </Badge>
          </div>

          <h2 className="text-xl font-semibold leading-snug text-white sm:text-2xl">
            {question.prompt}
          </h2>

          <div className="rounded-xl border border-border/70 bg-[#0f1018] px-4 py-3">
            <p className="text-sm leading-relaxed text-muted-foreground italic">
              “{question.evaluatorNotes}”
            </p>
          </div>

          <div className="rounded-xl border border-border/70 bg-[#0b0c12] p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                  Candidate Audio Input
                </p>
                <p className="mt-1 inline-flex items-center gap-2 text-xs text-emerald-300">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                  Live Feed • Active
                </p>
              </div>
              <div className="flex items-center gap-2">
                <MicrophoneStatus
                  isMuted={isMuted}
                  isSpeaking={isCandidateSpeaking && !isMuted}
                />
                <AiThinking isThinking={isAiThinking} />
              </div>
            </div>
            <VoiceWave isActive={isCandidateSpeaking && !isMuted} />
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
