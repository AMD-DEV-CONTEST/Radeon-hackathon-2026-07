"use client";

import { motion } from "framer-motion";
import { Star } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { InterviewHighlight } from "@/features/presentation/types/presentation.types";

interface InterviewHighlightsProps {
  highlights: ReadonlyArray<InterviewHighlight>;
}

export function InterviewHighlights({
  highlights,
}: InterviewHighlightsProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.12 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <Star className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Interview Highlights
            </h2>
          </div>

          <ul className="space-y-3" aria-label="Interview highlights">
            {highlights.map((item, index) => (
              <motion.li
                key={item.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.22, delay: 0.03 * index }}
                className="rounded-xl border border-white/5 bg-[#0f1018] p-3"
              >
                <Badge
                  variant="outline"
                  className="mb-2 tracking-normal normal-case"
                >
                  {item.label}
                </Badge>
                <p className="text-sm font-medium text-white">{item.title}</p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  {item.detail}
                </p>
              </motion.li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
