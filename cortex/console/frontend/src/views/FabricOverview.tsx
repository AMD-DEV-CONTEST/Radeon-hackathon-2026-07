import clsx from "clsx";

export interface Tenant { slug: string; org_did?: string; }

export interface OverviewEvent {
  event: string;
  data: { article?: { id: string; type?: string }; route?: { from: string; to: string } };
}

export interface FabricOverviewProps {
  tenants: Tenant[];
  events: OverviewEvent[];
}

export function FabricOverview({ tenants, events }: FabricOverviewProps) {
  const left = tenants[0] ?? { slug: "soc-alpha" };
  const right = tenants[1] ?? { slug: "soc-beta" };
  const lastRoute = events.filter(e => e.event === "article.published" && e.data.route).slice(-1)[0];
  return (
    <div className="grid grid-cols-2 gap-4 relative">
      <TenantColumn t={left} />
      <TenantColumn t={right} />
      <div data-flow className={clsx("absolute left-1/2 top-1/2 h-0.5 w-1/3 -translate-y-1/2 border-t-2 border-dotted border-indigo-400",
        lastRoute ? "animate-pulse" : "opacity-20")} />
    </div>
  );
}

function TenantColumn({ t }: { t: Tenant }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded p-4">
      <div className="text-lg font-bold text-slate-100">{t.slug}</div>
      <div className="text-xs text-slate-400">{t.org_did ?? ""}</div>
    </div>
  );
}
