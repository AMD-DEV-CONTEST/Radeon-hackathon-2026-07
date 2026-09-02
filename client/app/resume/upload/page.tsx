import type { Metadata } from "next";

import { ResumeUploadView } from "@/features/resume/components/resume-upload-view";

export const metadata: Metadata = {
  title: "Upload Resume — AgentVox",
  description:
    "Upload a candidate resume for AI-powered analysis and interview planning.",
};

export default function ResumeUploadPage() {
  return <ResumeUploadView />;
}
