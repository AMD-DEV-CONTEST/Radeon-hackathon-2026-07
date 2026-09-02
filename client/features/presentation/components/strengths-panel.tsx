"use client";

import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

interface StrengthsPanelProps {
  strengths: ReadonlyArray<string>;
}

export function StrengthsPanel({ strengths }: StrengthsPanelProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.1 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-secondary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Strengths
            </h2>
          </div>
          <ul className="space-y-3" aria-label="Strengths">
            {strengths.map((item, index) => (
              <motion.li
                key={item}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.2, delay: 0.03 * index }}
                className="rounded-xl border border-secondary/20 bg-secondary/5 px-3 py-2 text-sm text-muted-foreground"
              >
                {item}
              </motion.li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
