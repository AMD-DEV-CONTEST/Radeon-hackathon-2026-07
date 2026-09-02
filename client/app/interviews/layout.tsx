import type { ReactNode } from "react";

import { QueryProvider } from "@/providers/query-provider";

interface InterviewsLayoutProps {
  children: ReactNode;
}

export default function InterviewsLayout({ children }: InterviewsLayoutProps) {
  return <QueryProvider>{children}</QueryProvider>;
}
