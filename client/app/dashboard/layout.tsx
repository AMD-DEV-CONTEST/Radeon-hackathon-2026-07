import type { ReactNode } from "react";

import { QueryProvider } from "@/providers/query-provider";

interface DashboardRouteLayoutProps {
  children: ReactNode;
}

export default function DashboardRouteLayout({
  children,
}: DashboardRouteLayoutProps) {
  return <QueryProvider>{children}</QueryProvider>;
}
