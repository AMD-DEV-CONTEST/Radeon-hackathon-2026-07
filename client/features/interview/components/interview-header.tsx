"use client";

import { motion } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { InterviewTimer } from "@/features/interview/components/interview-timer";
import type { InterviewQuestion } from "@/features/interview/types/interview.types";

interface InterviewHeaderProps {
  question: InterviewQuestion;
}

export function InterviewHeader({ question }: InterviewHeaderProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="flex flex-wrap items-center gap-2"
    >
      <Badge variant="purple">
        Question {String(question.index).padStart(2, "0")} /{" "}
        {String(question.total).padStart(2, "0")}
      </Badge>
      <InterviewTimer elapsedSeconds={question.elapsedSeconds} />
      <Badge variant="secondary" className="normal-case">
        Topic: {question.topic}
      </Badge>
    </motion.div>
  );
}
