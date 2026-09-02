import type { ReactNode } from "react";

import { QueryProvider } from "@/providers/query-provider";

interface PresentationLayoutProps {
  children: ReactNode;
}

export default function PresentationLayout({
  children,
}: PresentationLayoutProps) {
  return <QueryProvider>{children}</QueryProvider>;
}
