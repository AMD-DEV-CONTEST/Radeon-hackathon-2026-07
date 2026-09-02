import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";

import { cn } from "@/lib/utils";

interface EmptyStateProps {
  title: string;
  description: string;
  icon?: LucideIcon;
  className?: string;
}

export function EmptyState({
  title,
  description,
  icon: Icon = Inbox,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-2xl border border-border/70 bg-[#12121a]/70 px-6 py-12 text-center",
        className
      )}
    >
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </div>
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">{description}</p>
    </div>
  );
}
