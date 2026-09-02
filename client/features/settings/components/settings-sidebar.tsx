"use client";

import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import {
  Accessibility,
  Bot,
  ChevronRight,
  KeyRound,
  Mic,
  MonitorSmartphone,
  Palette,
  Shield,
  SlidersHorizontal,
  TriangleAlert,
  UserRound,
  Bell,
} from "lucide-react";

import { Progress } from "@/components/ui/progress";
import { useSettingsStore } from "@/features/settings/store/settings.store";
import type {
  SettingsSection,
  StorageUsage,
} from "@/features/settings/types/settings.types";
import { cn } from "@/lib/utils";

interface SettingsSidebarProps {
  storage: StorageUsage;
}

const NAV_ITEMS: ReadonlyArray<{
  id: SettingsSection;
  label: string;
  icon: LucideIcon;
}> = [
  { id: "profile", label: "Profile", icon: UserRound },
  { id: "account", label: "Account", icon: SlidersHorizontal },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "interview", label: "Interview", icon: Accessibility },
  { id: "ai", label: "AI", icon: Bot },
  { id: "apiKeys", label: "API Keys", icon: KeyRound },
  { id: "security", label: "Security", icon: Shield },
  { id: "devices", label: "Devices", icon: Mic },
  { id: "danger", label: "Danger Zone", icon: TriangleAlert },
];

export function SettingsSidebar({ storage }: SettingsSidebarProps) {
  const activeSection = useSettingsStore((state) => state.activeSection);
  const setActiveSection = useSettingsStore((state) => state.setActiveSection);

  return (
    <aside
      className="rounded-2xl border border-white/10 bg-[#12121a]/80 p-4 backdrop-blur-xl"
      aria-label="Settings sections"
    >
      <p className="mb-3 px-2 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
        Preferences
      </p>
      <nav className="space-y-1">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = activeSection === item.id;

          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setActiveSection(item.id)}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-sm transition-colors",
                isActive
                  ? "bg-primary/15 text-white"
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
                <ChevronRight className="h-4 w-4 text-primary" aria-hidden="true" />
              ) : null}
            </button>
          );
        })}
      </nav>

      <div className="mt-6 border-t border-white/10 pt-4">
        <p className="mb-3 px-2 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
          Account Health
        </p>
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-white/10 bg-[#0f1018] p-3"
        >
          <div className="mb-2 flex items-center gap-2">
            <MonitorSmartphone className="h-4 w-4 text-primary" aria-hidden="true" />
            <p className="text-sm font-medium text-white">Storage Usage</p>
          </div>
          <div className="mb-1.5 flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Used</span>
            <span className="font-semibold text-white">{storage.percent}%</span>
          </div>
          <Progress value={storage.percent} className="h-1.5" />
          <p className="mt-2 text-xs text-muted-foreground">
            {storage.usedGb}GB of {storage.totalGb}GB used
          </p>
        </motion.div>
      </div>
    </aside>
  );
}
