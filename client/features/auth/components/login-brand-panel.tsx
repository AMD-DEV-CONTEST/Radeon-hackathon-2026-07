"use client";

import { motion } from "framer-motion";
import { Cpu, Eye, Network, Shield, Sparkles } from "lucide-react";

import { Logo } from "@/components/shared/logo";
import { Card, CardContent } from "@/components/ui/card";
import Image from "next/image";

const FEATURES = [
  {
    title: "Autonomous Orchestration",
    description:
      "LangGraph-powered agents specialized in technical and behavioral analysis.",
    icon: Cpu,
  },
  {
    title: "Real-time Visualization",
    description:
      "Monitor live transcripts and sentiment metrics through a high-fidelity command center.",
    icon: Eye,
  },
  {
    title: "Enterprise Compliance",
    description:
      "Full GDPR support with encrypted storage for candidate PII and recordings.",
    icon: Shield,
  },
  {
    title: "ROCm Accelerated",
    description:
      "Optimized inference pipelines delivering sub-second voice assessment latency.",
    icon: Network,
  },
] as const;

export function LoginBrandPanel() {
  return (
    <motion.section
      initial={{ opacity: 0, x: -16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
      className="relative hidden min-h-screen flex-col justify-between overflow-hidden bg-[#050505] px-8 py-8 lg:flex xl:px-12"
      aria-label="AgentVox product highlights"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,_rgba(139,92,246,0.18)_0%,_transparent_55%)]"
      />

      <div className="relative z-10">
        <Logo />

        <div className="mt-12 max-w-xl">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-primary/35 bg-primary/10 px-3 py-1.5">
            <Sparkles className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
            <span className="text-[11px] font-semibold tracking-[0.14em] text-primary uppercase">
              The future of technical hiring
            </span>
          </div>

          <h2 className="text-4xl font-bold leading-tight tracking-tight text-white xl:text-5xl">
            Experience <span className="gradient-text">Multi-Agent</span>{" "}
            Interviewing
          </h2>
          <p className="mt-4 max-w-lg text-sm leading-relaxed text-muted-foreground xl:text-base">
            Harness the power of Vox-1, our proprietary AI engine, to conduct
            sub-second latency voice assessments and receive deep analytical
            insights for every candidate.
          </p>
        </div>

        {/* <div className="relative mt-10 overflow-hidden rounded-2xl border border-border/70 bg-card/40">
          cccc
          <div
            aria-hidden="true"
            className="aspect-[16/9] bg-[radial-gradient(circle_at_30%_40%,_rgba(139,92,246,0.35),_transparent_45%),radial-gradient(circle_at_70%_60%,_rgba(59,130,246,0.25),_transparent_40%),linear-gradient(135deg,#111827,#0a0a0f)]"
          />
          <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 border-t border-border/60 bg-black/45 px-4 py-3 backdrop-blur-sm">
            <div className="flex items-center gap-2 text-xs text-white/80">
              <span className="h-2 w-2 rounded-full bg-sky-400" />
              VOX-ENGINE V2.4.0 LIVE
            </div>
            <div className="flex items-center gap-4 text-[11px]">
              <span className="text-muted-foreground">LATENCY: 124ms</span>
              <span className="text-primary">SYNC: OPTIMAL</span>
            </div>
          </div>
        </div> */}
        <Image src={"/auth/image.png"} alt="ss" height={600} width={1000} />

        {/* <div className="mt-6 grid grid-cols-2 gap-3">
          {FEATURES.map((feature) => {
            const Icon = feature.icon;

            return (
              <Card
                key={feature.title}
                className="rounded-xl border border-border/70 bg-card/60 py-0 ring-0"
              >
                <CardContent className="p-4">
                  <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-lg bg-primary/15 text-primary">
                    <Icon className="h-4 w-4" aria-hidden="true" />
                  </div>
                  <h3 className="text-sm font-semibold text-white">
                    {feature.title}
                  </h3>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {feature.description}
                  </p>
                </CardContent>
              </Card>
            );
          })}
        </div> */}
      </div>

      <div className="relative z-10 mt-8 flex items-center justify-between gap-4 text-xs text-muted-foreground">
        <p>© 2026 AgentVox AI. All rights reserved.</p>
        <div className="flex items-center gap-4">
          <a href="#" className="transition-colors hover:text-white">
            Privacy
          </a>
          <a href="#" className="transition-colors hover:text-white">
            Security
          </a>
          <a href="#" className="transition-colors hover:text-white">
            Status
          </a>
        </div>
      </div>
    </motion.section>
  );
}
