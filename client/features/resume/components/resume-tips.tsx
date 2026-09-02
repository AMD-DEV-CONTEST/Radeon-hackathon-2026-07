"use client";

import { motion } from "framer-motion";
import {
  Brain,
  Clock3,
  Cpu,
  Crosshair,
  Info,
} from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

const TIP_ITEMS = [
  {
    title: "~15 Seconds",
    description: "Estimated analysis time",
    icon: Clock3,
  },
  {
    title: "Deep Skill Mapping",
    description: "Identifies 20+ technical clusters",
    icon: Cpu,
  },
  {
    title: "Gap Identification",
    description: "Highlights areas for technical growth",
    icon: Crosshair,
  },
] as const;

export function ResumeTips() {
  return (
    <motion.aside
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.08 }}
      className="h-fit rounded-2xl border border-border/70 bg-[#12121a] p-5"
      aria-label="AI guidance"
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/15 text-primary">
            <Brain className="h-4 w-4" aria-hidden="true" />
          </div>
          <h2 className="text-lg font-semibold text-white">AI Guidance</h2>
        </div>
        <span className="text-xs font-medium text-primary">Vox-1 Engine</span>
      </div>

      <p className="text-sm leading-relaxed text-muted-foreground">
        Our specialized Analysis Agent identifies key strengths and
        architectural gaps to ensure a deep technical evaluation.
      </p>

      <Card className="mt-5 overflow-hidden rounded-xl border border-border/70 bg-[#0d0d14] py-0 ring-0">
        <CardContent className="relative p-0">
          <div
            aria-hidden="true"
            className="aspect-[16/10] bg-[radial-gradient(circle_at_30%_40%,rgba(139,92,246,0.35),transparent_45%),radial-gradient(circle_at_70%_65%,rgba(59,130,246,0.28),transparent_40%),linear-gradient(160deg,#111827,#09090b)]"
          />
          <div className="absolute inset-x-0 bottom-0 space-y-1 bg-gradient-to-t from-black/80 via-black/45 to-transparent px-4 py-4">
            <p className="text-xs font-semibold tracking-[0.14em] text-white uppercase">
              Neural Parser Active
            </p>
            <p className="text-xs italic text-muted-foreground">
              “Extracting multi-dimensional semantic patterns...”
            </p>
          </div>
        </CardContent>
      </Card>

      <ul className="mt-4 space-y-3">
        {TIP_ITEMS.map((item, index) => {
          const Icon = item.icon;

          return (
            <motion.li
              key={item.title}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.12 + index * 0.05 }}
              className="flex items-start gap-3 rounded-xl border border-border/60 bg-[#0f1018] p-3 transition-colors hover:border-primary/25"
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
                <Icon className="h-4 w-4" aria-hidden="true" />
              </div>
              <div>
                <p className="text-sm font-semibold text-white">{item.title}</p>
                <p className="text-[11px] tracking-[0.08em] text-muted-foreground uppercase">
                  {item.description}
                </p>
              </div>
            </motion.li>
          );
        })}
      </ul>

      <div className="mt-5 rounded-xl border border-primary/30 bg-primary/5 p-4">
        <div className="mb-2 flex items-center gap-2 text-primary">
          <Info className="h-4 w-4" aria-hidden="true" />
          <p className="text-xs font-semibold tracking-[0.14em] uppercase">
            Pro Tip
          </p>
        </div>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Ensure your project descriptions highlight specific architecture
          choices.
        </p>
      </div>
    </motion.aside>
  );
}
