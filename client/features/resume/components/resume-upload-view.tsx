"use client";

import { motion } from "framer-motion";

import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Badge } from "@/components/ui/badge";
import { ResumeTips } from "@/features/resume/components/resume-tips";
import { UploadCard } from "@/features/resume/components/upload-card";

export function ResumeUploadView() {
  return (
    <DashboardLayout
      breadcrumbs={[
        { label: "Interview Management" },
        { label: "Active Sessions", current: true },
      ]}
    >
      <div className="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_360px]">
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="min-w-0 space-y-6"
        >
          <header className="space-y-3">
            <Badge variant="purple">Candidate Onboarding</Badge>
            <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Upload Your Resume
            </h1>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
              Upload your latest professional history and let AgentVox AI
              prepare a personalized, high-fidelity technical interview script.
            </p>
          </header>

          <UploadCard />
        </motion.div>

        <ResumeTips />
      </div>
    </DashboardLayout>
  );
}
