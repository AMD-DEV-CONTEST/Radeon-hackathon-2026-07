"use client";

import { motion } from "framer-motion";
import {
  CalendarPlus,
  Download,
  FileText,
  Share2,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

interface ReportActionsProps {
  reportId: string;
  interviewId: string;
  onViewTranscript?: () => void;
}

export function ReportActions({
  reportId,
  interviewId,
  onViewTranscript,
}: ReportActionsProps) {
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  function announce(message: string) {
    setStatusMessage(message);
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.16 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h3 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Report Actions
          </h3>

          <div
            className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
            role="group"
            aria-label="Interview report actions"
          >
            <Button
              type="button"
              variant="outline"
              className="h-11 justify-start"
              onClick={() =>
                announce(`PDF download prepared for report ${reportId}`)
              }
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              Download PDF
            </Button>
            <Button
              type="button"
              variant="outline"
              className="h-11 justify-start"
              onClick={() =>
                announce(`Share link copied for report ${reportId}`)
              }
            >
              <Share2 className="h-4 w-4" aria-hidden="true" />
              Share Report
            </Button>
            <Button
              type="button"
              variant="outline"
              className="h-11 justify-start"
              onClick={() => {
                onViewTranscript?.();
                announce(`Opening transcript for interview ${interviewId}`);
              }}
            >
              <FileText className="h-4 w-4" aria-hidden="true" />
              View Transcript
            </Button>
            <Button
              type="button"
              className="h-11 justify-start glow-purple"
              onClick={() =>
                announce(
                  `Re-interview scheduling started for interview ${interviewId}`
                )
              }
            >
              <CalendarPlus className="h-4 w-4" aria-hidden="true" />
              Schedule Re-Interview
            </Button>
          </div>

          <p className="sr-only" role="status" aria-live="polite">
            {statusMessage}
          </p>
          {statusMessage ? (
            <p className="mt-3 text-xs text-muted-foreground" aria-hidden="true">
              {statusMessage}
            </p>
          ) : null}
        </CardContent>
      </Card>
    </motion.div>
  );
}
