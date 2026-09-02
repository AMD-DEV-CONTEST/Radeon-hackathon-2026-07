"use client";

import { motion } from "framer-motion";

import { RecommendationCard } from "@/features/presentation/components/recommendation-card";
import type {
  HiringRecommendation as HiringRecommendationValue,
} from "@/features/presentation/types/presentation.types";

interface HiringDecisionProps {
  recommendation: HiringRecommendationValue;
  explanation: string;
}

export function HiringDecision({
  recommendation,
  explanation,
}: HiringDecisionProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.12 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <RecommendationCard
        recommendation={recommendation}
        explanation={explanation}
        className="h-full border-primary/30 bg-gradient-to-b from-primary/10 to-[#12121a]/90"
      />
    </motion.div>
  );
}
