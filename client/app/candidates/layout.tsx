import type { ReactNode } from "react";

import { QueryProvider } from "@/providers/query-provider";

interface CandidatesLayoutProps {
  children: ReactNode;
}

export default function CandidatesLayout({ children }: CandidatesLayoutProps) {
  return <QueryProvider>{children}</QueryProvider>;
}
