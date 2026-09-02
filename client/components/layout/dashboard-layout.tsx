"use client";

import { Menu, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { AppTopbar } from "@/components/layout/app-topbar";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface DashboardLayoutProps {
  children: ReactNode;
  breadcrumbs?: ReadonlyArray<{ label: string; current?: boolean }>;
}

export function DashboardLayout({
  children,
  breadcrumbs,
}: DashboardLayoutProps) {
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-[#09090b] text-white">
      <div className="hidden lg:block">
        <div className="sticky top-0 h-screen">
          <AppSidebar />
        </div>
      </div>

      {isMobileNavOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/60"
            aria-label="Close navigation overlay"
            onClick={() => setIsMobileNavOpen(false)}
          />
          <div className="relative z-50 h-full w-64 max-w-[85vw]">
            <AppSidebar />
          </div>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-border/70 lg:border-b-0">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="ml-2 lg:hidden"
            aria-label={isMobileNavOpen ? "Close menu" : "Open menu"}
            onClick={() => setIsMobileNavOpen((previous) => !previous)}
          >
            {isMobileNavOpen ? (
              <X className="h-5 w-5" />
            ) : (
              <Menu className="h-5 w-5" />
            )}
          </Button>
          <div className={cn("min-w-0 flex-1")}>
            <AppTopbar breadcrumbs={breadcrumbs} />
          </div>
        </div>

        <main className="flex-1 overflow-x-hidden">{children}</main>
      </div>
    </div>
  );
}
