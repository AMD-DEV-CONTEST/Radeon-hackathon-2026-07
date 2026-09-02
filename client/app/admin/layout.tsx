import type { ReactNode } from "react";

import { QueryProvider } from "@/providers/query-provider";

interface AdminLayoutProps {
  children: ReactNode;
}

export default function AdminLayout({ children }: AdminLayoutProps) {
  return <QueryProvider>{children}</QueryProvider>;
}
