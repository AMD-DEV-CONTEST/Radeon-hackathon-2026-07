import type { ReactNode } from "react";

import { QueryProvider } from "@/providers/query-provider";

interface ResumeLayoutProps {
  children: ReactNode;
}

export default function ResumeLayout({ children }: ResumeLayoutProps) {
  return <QueryProvider>{children}</QueryProvider>;
}
