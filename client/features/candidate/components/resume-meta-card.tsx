"use client";

import { motion } from "framer-motion";
import { FileText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { ResumeDetails } from "@/features/candidate/types/candidate.types";

interface ResumeMetaCardProps {
  resume: ResumeDetails;
}

function formatFileSize(bytes: number): string {
  if (bytes <= 0) {
    return "—";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatUploadedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

export function ResumeMetaCard({ resume }: ResumeMetaCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-4 p-5">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" aria-hidden="true" />
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Resume
            </h3>
          </div>

          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p
                className="truncate text-sm font-semibold text-white"
                title={resume.fileName}
              >
                {resume.fileName}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Uploaded {formatUploadedAt(resume.uploadedAt)}
              </p>
            </div>
            <Badge variant="purple" className="shrink-0 capitalize">
              {resume.status}
            </Badge>
          </div>

          <dl className="grid grid-cols-2 gap-3 text-xs">
            <div className="rounded-lg border border-border/70 bg-[#0f1018] px-3 py-2">
              <dt className="text-muted-foreground">File size</dt>
              <dd className="mt-1 font-medium text-white">
                {formatFileSize(resume.fileSize)}
              </dd>
            </div>
            <div className="rounded-lg border border-border/70 bg-[#0f1018] px-3 py-2">
              <dt className="text-muted-foreground">Type</dt>
              <dd className="mt-1 truncate font-medium text-white" title={resume.mimeType}>
                {resume.mimeType || "—"}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </motion.div>
  );
}
