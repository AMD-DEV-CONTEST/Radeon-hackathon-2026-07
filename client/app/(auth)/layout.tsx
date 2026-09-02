import type { ReactNode } from "react";

import { QueryProvider } from "@/providers/query-provider";

interface AuthLayoutProps {
  children: ReactNode;
}

export default function AuthLayout({ children }: AuthLayoutProps) {
  return <QueryProvider>{children}</QueryProvider>;
}
