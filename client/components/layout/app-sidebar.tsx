"use client";

import {
  BarChart3,
  ChevronRight,
  CircleHelp,
  LayoutDashboard,
  Settings,
  Users,
  Video,
  Radio,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/shared/logo";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Candidates", href: "/candidates/dossier", icon: Users },
  { label: "Interviews", href: "/interviews/planning", icon: Video },
  { label: "Analytics", href: "/analytics", icon: BarChart3 },
  { label: "Settings", href: "/settings", icon: Settings },
] as const;

function isNavItemActive(pathname: string, href: string): boolean {
  if (pathname === href) {
    return true;
  }

  if (href === "/candidates/dossier") {
    return pathname.startsWith("/candidates");
  }

  if (href === "/interviews/planning") {
    return pathname.startsWith("/interviews");
  }

  if (href === "/resume/upload") {
    return pathname.startsWith("/resume");
  }

  return pathname.startsWith(`${href}/`);
}

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="flex h-full w-64 shrink-0 flex-col border-r border-border/70 bg-[#0b0b10]"
      aria-label="Primary"
    >
      <div className="px-5 py-5">
        <Logo />
      </div>

      <nav className="flex-1 space-y-1 px-3" aria-label="Main">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = isNavItemActive(pathname, item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "group flex items-center justify-between rounded-xl px-3 py-2.5 text-sm transition-colors",
                isActive
                  ? "bg-white/5 text-white"
                  : "text-muted-foreground hover:bg-white/5 hover:text-white"
              )}
            >
              <span className="flex items-center gap-3">
                <Icon
                  className={cn(
                    "h-4 w-4",
                    isActive ? "text-primary" : "text-muted-foreground"
                  )}
                  aria-hidden="true"
                />
                {item.label}
              </span>
              {isActive ? (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              ) : null}
            </Link>
          );
        })}
      </nav>

      <div className="space-y-3 px-4 pb-5">
        <div className="rounded-xl border border-border/70 bg-[#12121a] p-3">
          <p className="text-[10px] font-semibold tracking-[0.16em] text-muted-foreground uppercase">
            Active Agent
          </p>
          <div className="mt-2 flex items-start gap-2.5">
            <div className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg bg-primary/15 text-primary">
              <Radio className="h-4 w-4 animate-pulse" aria-hidden="true" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">Vox-1</p>
              <p className="text-xs text-muted-foreground">
                Analyzing response...
              </p>
            </div>
          </div>
        </div>

        <Link
          href="#"
          className="flex items-center gap-2.5 rounded-xl px-2 py-2 text-sm text-muted-foreground transition-colors hover:text-white"
        >
          <CircleHelp className="h-4 w-4" aria-hidden="true" />
          Help & Support
        </Link>
      </div>
    </aside>
  );
}
