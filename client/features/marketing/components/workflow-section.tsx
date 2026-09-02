"use client";

import { motion } from "framer-motion";

import { SectionHeader } from "@/components/common/section-header";
import { WorkflowStep } from "@/features/marketing/components/workflow-step";
import { LANDING_WORKFLOW } from "@/features/marketing/constants";

export function WorkflowSection() {
  return (
    <section
      id="workflow"
      className="scroll-mt-24 border-y border-border py-20 sm:py-24"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <SectionHeader
          title="The AgentVox Workflow"
          description="From resume upload to hiring decision — a fully automated, AI-driven interview pipeline."
        />

        <motion.div
          initial={{ opacity: 0, y: 18 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-40px" }}
          transition={{ duration: 0.45 }}
          className="mt-14 flex flex-col items-center gap-10 md:flex-row md:items-start md:justify-between md:gap-4"
        >
          {LANDING_WORKFLOW.map((step, index) => (
            <WorkflowStep
              key={step.step}
              step={step.step}
              title={step.title}
              description={step.description}
              showConnector={index < LANDING_WORKFLOW.length - 1}
            />
          ))}
        </motion.div>
      </div>
    </section>
  );
}
