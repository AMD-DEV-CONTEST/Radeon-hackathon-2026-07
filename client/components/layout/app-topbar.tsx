"use client";

import { Bell, ChevronDown, Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { useLogout } from "@/features/auth/hooks/use-logout";
import { useAuthStore } from "@/features/auth/store/auth.store";

interface AppTopbarProps {
  breadcrumbs?: ReadonlyArray<{ label: string; current?: boolean }>;
}

function getUserInitials(fullName: string | undefined): string {
  if (!fullName) {
    return "AJ";
  }

  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return "AJ";
  }

  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }

  return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase();
}

export function AppTopbar({
  breadcrumbs = [
    { label: "Interview Management" },
    { label: "Active Sessions", current: true },
  ],
}: AppTopbarProps) {
  const user = useAuthStore((state) => state.user);
  const logoutMutation = useLogout();
  const initials = getUserInitials(user?.fullName);

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-4 border-b border-border/70 bg-[#0b0b10]/90 px-4 backdrop-blur-xl sm:px-6">
      <nav aria-label="Breadcrumb" className="min-w-0">
        <ol className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          {breadcrumbs.map((crumb, index) => (
            <li key={crumb.label} className="flex items-center gap-2">
              {index > 0 ? <span aria-hidden="true">/</span> : null}
              <span
                className={
                  crumb.current ? "font-medium text-white" : undefined
                }
                aria-current={crumb.current ? "page" : undefined}
              >
                {crumb.label}
              </span>
            </li>
          ))}
        </ol>
      </nav>

      <div className="flex items-center gap-3">
        <div className="relative hidden w-64 md:block lg:w-80">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            type="search"
            placeholder="Search candidates, sessions..."
            aria-label="Search candidates and sessions"
            className="h-10 rounded-full bg-[#12121a] pl-10"
          />
        </div>

        <button
          type="button"
          aria-label="Notifications"
          className="relative flex h-10 w-10 items-center justify-center rounded-full border border-border/70 bg-[#12121a] text-muted-foreground transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        >
          <Bell className="h-4 w-4" aria-hidden="true" />
          <span className="absolute top-2.5 right-2.5 h-2 w-2 rounded-full bg-primary" />
        </button>

        <button
          type="button"
          className="flex items-center gap-2 rounded-full border border-border/70 bg-[#12121a] py-1 pr-2 pl-1 text-sm text-white transition-colors hover:border-primary/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-60"
          aria-label={logoutMutation.isPending ? "Signing out" : "Sign out"}
          disabled={logoutMutation.isPending}
          onClick={() => {
            void logoutMutation.mutateAsync();
          }}
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-primary">
            {initials}
          </span>
          <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
