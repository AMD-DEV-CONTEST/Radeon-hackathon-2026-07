import type { ReactNode } from "react";

import { QueryProvider } from "@/providers/query-provider";

interface SettingsLayoutProps {
  children: ReactNode;
}

export default function SettingsLayout({ children }: SettingsLayoutProps) {
  return <QueryProvider>{children}</QueryProvider>;
}
