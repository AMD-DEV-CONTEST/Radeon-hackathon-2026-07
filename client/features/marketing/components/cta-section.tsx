"use client";

import { motion } from "framer-motion";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function CtaSection() {
  return (
    <section id="cta" className="scroll-mt-24 py-20 sm:py-24">
      <div className="relative mx-auto max-w-3xl px-4 text-center sm:px-6">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 -z-10 rounded-full bg-primary/15 blur-3xl"
        />

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-40px" }}
          transition={{ duration: 0.45 }}
        >
          <h2 className="text-3xl font-bold tracking-tight text-white md:text-4xl">
            Ready to Scale Your Engineering Team?
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
            Join engineering teams using AgentVox to conduct smarter, faster
            technical interviews with multi-agent AI.
          </p>

          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row sm:gap-4">
            <Link
              href="/register"
              className={cn(
                buttonVariants({ size: "lg" }),
                "h-11 w-full px-6 glow-purple sm:w-auto"
              )}
            >
              Start Free Trial
            </Link>
            <Link
              href="#features"
              className={cn(
                buttonVariants({ variant: "outline", size: "lg" }),
                "h-11 w-full px-6 sm:w-auto"
              )}
            >
              Talk to Sales
            </Link>
          </div>

          <p className="mt-4 text-xs text-muted-foreground">
            No credit card required. Cancel anytime.
          </p>
        </motion.div>
      </div>
    </section>
  );
}
