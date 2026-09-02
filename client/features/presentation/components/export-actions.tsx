"use client";

import { motion } from "framer-motion";
import {
  Download,
  FileText,
  Printer,
  Share2,
  Play,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface ExportActionsProps {
  reportId: string;
  candidateId: string;
}

export function ExportActions({ reportId, candidateId }: ExportActionsProps) {
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.16 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Actions
          </h2>

          <div
            className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"
            role="group"
            aria-label="Presentation actions"
          >
            <Button
              type="button"
              variant="outline"
              className="h-11 justify-start"
              onClick={() =>
                setStatusMessage(`PDF download prepared for report ${reportId}`)
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
                setStatusMessage(`Share link copied for report ${reportId}`)
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
                window.print();
                setStatusMessage("Print dialog opened");
              }}
            >
              <Printer className="h-4 w-4" aria-hidden="true" />
              Print
            </Button>
            <Link
              href={`/interviews/report?id=${reportId}`}
              className={cn(
                buttonVariants({ variant: "outline" }),
                "h-11 justify-start"
              )}
            >
              <FileText className="h-4 w-4" aria-hidden="true" />
              View Transcript
            </Link>
            <Link
              href={`/interviews/planning?candidateId=${candidateId}`}
              className={cn(
                buttonVariants(),
                "h-11 justify-start glow-purple"
              )}
            >
              <Play className="h-4 w-4" aria-hidden="true" />
              Start New Interview
            </Link>
          </div>

          <p className="sr-only" role="status" aria-live="polite">
            {statusMessage}
          </p>
          {statusMessage ? (
            <p className="mt-3 text-xs text-muted-foreground">{statusMessage}</p>
          ) : null}
        </CardContent>
      </Card>
    </motion.div>
  );
}
