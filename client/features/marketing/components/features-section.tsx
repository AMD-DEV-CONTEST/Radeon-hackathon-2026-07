"use client";

import { motion } from "framer-motion";

import { SectionHeader } from "@/components/common/section-header";
import { FeatureCard } from "@/features/marketing/components/feature-card";
import { LANDING_FEATURES } from "@/features/marketing/constants";

export function FeaturesSection() {
  return (
    <section id="features" className="scroll-mt-24 py-20 sm:py-24">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <SectionHeader
          title="Enterprise-Grade AI Capabilities"
          description="Specialized AI agents working in concert to deliver the most comprehensive technical interview experience."
        />

        <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3 lg:gap-6">
          {LANDING_FEATURES.map((feature, index) => (
            <motion.div
              key={feature.title}
              initial={{ opacity: 0, y: 18 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-40px" }}
              transition={{ duration: 0.4, delay: index * 0.05 }}
            >
              <FeatureCard
                title={feature.title}
                description={feature.description}
                icon={feature.icon}
                className="h-full"
              />
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
