import { useEffect, useRef } from "react";
import { Network, DataSet } from "vis-network";

export interface GraphArticle {
  id: string;
  type: string;
  content: string;
  trust_score?: number | null;
  cites?: string[];
}

export interface ProvenanceGraphProps { articles: GraphArticle[]; }

export function ProvenanceGraph({ articles }: ProvenanceGraphProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const nodes = new DataSet(articles.map(a => ({
      id: a.id,
      label: a.content.slice(0, 24),
      color: { background: colorFromTrust(a.trust_score ?? 0.5) },
    })));
    const edges = articles.flatMap(a => (a.cites ?? []).map(to => ({ from: a.id, to })));
    new Network(ref.current, { nodes, edges: new DataSet(edges) }, { physics: { stabilization: true } });
  }, [articles]);
  return <div ref={ref} className="w-full h-[600px] bg-slate-900 border border-slate-800 rounded" />;
}

function colorFromTrust(t: number): string {
  if (t >= 0.7) return "#16a34a";
  if (t >= 0.4) return "#eab308";
  return "#dc2626";
}
