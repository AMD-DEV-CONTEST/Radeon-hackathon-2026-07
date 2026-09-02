"use client";

import { motion } from "framer-motion";

import { Card, CardContent } from "@/components/ui/card";
import {
  LANDING_PARTNERS,
  LANDING_TRUST_PILLARS,
} from "@/features/marketing/constants";

export function TrustSection() {
  return (
    <section id="trust" className="scroll-mt-24 py-20 sm:py-24">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <p className="text-center text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">
          The companies building powerful teams
        </p>

        <div className="mt-8 flex flex-wrap items-center justify-center gap-x-8 gap-y-4 sm:gap-x-12">
          {LANDING_PARTNERS.map((partner) => (
            <span
              key={partner}
              className="text-sm font-semibold tracking-wide text-white/45 sm:text-base"
            >
              {partner}
            </span>
          ))}
        </div>

        <div className="mt-14 grid gap-5 md:grid-cols-3">
          {LANDING_TRUST_PILLARS.map((pillar, index) => {
            const Icon = pillar.icon;

            return (
              <motion.div
                key={pillar.title}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-40px" }}
                transition={{ duration: 0.4, delay: index * 0.06 }}
              >
                <Card className="h-full rounded-2xl border border-border/80 bg-card/70 py-0 ring-0">
                  <CardContent className="flex items-start gap-4 p-6">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/15 text-primary">
                      <Icon className="h-5 w-5" aria-hidden="true" />
                    </div>
                    <div>
                      <h3 className="text-base font-semibold text-white">
                        {pillar.title}
                      </h3>
                      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                        {pillar.description}
                      </p>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
