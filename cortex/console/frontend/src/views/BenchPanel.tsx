import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import type { MetricsSample } from "../hooks/useBrokerMetrics";

export interface BenchPanelProps { byNode: Record<string, MetricsSample[]>; }

export function BenchPanel({ byNode }: BenchPanelProps) {
  const flat = Object.values(byNode).flat();
  const embedData = flat.map(s => ({ name: s.node, radeon: s.embeds_per_sec_radeon, cpu: s.embeds_per_sec_cpu }));
  const queryData = flat.map(s => ({ name: s.node, radeon: s.queries_per_sec_radeon, cpu: s.queries_per_sec_cpu }));
  return (
    <div className="grid grid-cols-2 gap-4">
      <Chart data={embedData} title="Embeds/sec (Radeon vs CPU)" />
      <Chart data={queryData} title="Queries/sec (Radeon vs CPU)" />
    </div>
  );
}

function Chart({ data, title }: { data: { name: string; radeon: number; cpu: number }[]; title: string }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded p-4">
      <h3 className="text-sm font-semibold text-slate-300 mb-2">{title}</h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} layout="vertical">
          <XAxis type="number" stroke="#94a3b8" />
          <YAxis type="category" dataKey="name" stroke="#94a3b8" />
          <Tooltip />
          <Bar dataKey="radeon" fill="#f43f5e" />
          <Bar dataKey="cpu" fill="#3b82f6" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
