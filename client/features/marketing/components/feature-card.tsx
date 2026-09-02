import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface FeatureCardProps {
  title: string;
  description: string;
  icon: LucideIcon;
  className?: string;
}

export function FeatureCard({
  title,
  description,
  icon: Icon,
  className,
}: FeatureCardProps) {
  return (
    <Card
      className={cn(
        "rounded-2xl border border-border/80 bg-card/80 py-0 ring-0 transition-colors hover:border-primary/30",
        className
      )}
    >
      <CardContent className="p-6">
        <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-primary/15 text-primary">
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          {description}
        </p>
      </CardContent>
    </Card>
  );
}
