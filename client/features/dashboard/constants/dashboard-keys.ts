import type { QuickAction } from "@/features/dashboard/types/dashboard.types";

export const DASHBOARD_QUERY_KEYS = {
  all: ["dashboard"] as const,
  root: () => [...DASHBOARD_QUERY_KEYS.all, "root"] as const,
  candidate: (id: string) =>
    [...DASHBOARD_QUERY_KEYS.all, "candidate", id] as const,
  interviews: () => [...DASHBOARD_QUERY_KEYS.all, "interviews"] as const,
  reports: () => [...DASHBOARD_QUERY_KEYS.all, "reports"] as const,
} as const;

/** App-route quick actions (navigation wiring, not metric data). */
export const DASHBOARD_QUICK_ACTIONS: ReadonlyArray<QuickAction> = [
  {
    id: "qa-resume",
    label: "Upload Resume",
    href: "/resume/upload",
    description: "Refresh dossier signals",
  },
  {
    id: "qa-mock",
    label: "Start Interview",
    href: "/interviews/planning",
    description: "Launch multi-agent practice",
  },
  {
    id: "qa-reports",
    label: "View Reports",
    href: "/interviews/report",
    description: "Open latest evaluation",
  },
  {
    id: "qa-settings",
    label: "Settings",
    href: "/settings",
    description: "Preferences and notifications",
  },
] as const;
