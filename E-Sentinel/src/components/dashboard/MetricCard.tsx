import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

const INTENT_CLASS: Record<string, string> = {
  success: "text-success",
  danger: "text-destructive",
  warning: "text-warning",
  neutral: "text-foreground",
};

export default function MetricCard({
  label,
  value,
  unit,
  sub,
  trend,
  intent = "neutral",
}: {
  label: React.ReactNode;
  value: string | number;
  unit?: string;
  sub?: string;
  trend?: "up" | "down" | "flat";
  intent?: "success" | "danger" | "warning" | "neutral";
}) {
  return (
    <Card className="relative overflow-hidden border-border/60 shadow-none hover:shadow-md transition-shadow duration-300">
      <CardContent className="pt-4 pb-4">
        <p className="section-label mb-2">{label}</p>
        <div className="flex items-baseline gap-1.5">
          <span
            className={cn(
              "text-[26px] font-extrabold tracking-[-0.02em] tabular-nums leading-none",
              INTENT_CLASS[intent]
            )}
          >
            {value}
          </span>
          {unit && (
            <span className="text-xs text-muted-foreground font-medium">
              {unit}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 mt-2">
          {sub && <p className="text-[11px] text-muted-foreground">{sub}</p>}
          {trend && (
            <span
              className={cn(
                "inline-flex items-center gap-0.5 text-[11px] font-medium",
                trend === "up" && "metric-up",
                trend === "down" && "metric-down",
                trend === "flat" && "metric-flat"
              )}
            >
              {trend === "up" && <TrendingUp className="w-3 h-3" strokeWidth={2.5} />}
              {trend === "down" && <TrendingDown className="w-3 h-3" strokeWidth={2.5} />}
              {trend === "flat" && <Minus className="w-3 h-3" strokeWidth={2.5} />}
              {trend === "up" ? "上升" : trend === "down" ? "下降" : "持平"}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
