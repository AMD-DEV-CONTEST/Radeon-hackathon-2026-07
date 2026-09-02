import type { ReactNode } from "react";

import { QueryProvider } from "@/providers/query-provider";

interface AgentsLayoutProps {
  children: ReactNode;
}

export default function AgentsLayout({ children }: AgentsLayoutProps) {
  return <QueryProvider>{children}</QueryProvider>;
}
