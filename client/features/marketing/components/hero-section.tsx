"use client";

import { motion } from "framer-motion";
import { ArrowRight, Play } from "lucide-react";
import Link from "next/link";

import { HeroVisual } from "@/features/marketing/components/hero-visual";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function HeroSection() {
  return (
    <section className="relative overflow-hidden pt-28 pb-16 sm:pt-32 sm:pb-20">
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_rgba(139,92,246,0.18)_0%,_transparent_70%)]"
      />

      <div className="relative mx-auto max-w-4xl px-4 text-center sm:px-6">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        >
          <div className="mb-6 inline-flex items-center rounded-full border border-primary/30 bg-primary/10 px-4 py-1.5">
            <span className="text-xs font-medium tracking-wide text-primary">
              AI INTERVIEWS FOR THE MODERN ERA
            </span>
          </div>

          <h1 className="text-4xl font-bold leading-[1.1] tracking-tight text-white sm:text-5xl md:text-6xl lg:text-7xl">
            Meet Your{" "}
            <span className="gradient-text">AI Interview Panel</span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-muted-foreground sm:text-lg">
            Multi-agent AI orchestration for conducting comprehensive technical
            interviews with sub-second latency, real-time evaluation, and
            actionable hiring insights.
          </p>

          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row sm:gap-4">
            <Link
              href="/register"
              className={cn(
                buttonVariants({ size: "lg" }),
                "h-11 w-full px-6 glow-purple sm:w-auto"
              )}
            >
              Start your first interview
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
            <Link
              href="#features"
              className={cn(
                buttonVariants({ variant: "outline", size: "lg" }),
                "h-11 w-full px-6 sm:w-auto"
              )}
            >
              <Play className="h-4 w-4" aria-hidden="true" />
              Watch Demo
            </Link>
          </div>
        </motion.div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 28 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.15, ease: "easeOut" }}
      >
        <HeroVisual />
      </motion.div>
    </section>
  );
}
