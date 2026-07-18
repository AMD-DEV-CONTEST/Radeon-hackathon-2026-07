import { useEffect, useReducer } from "react";

export interface MetricsSample {
  node: string;
  embeds_per_sec_radeon: number;
  embeds_per_sec_cpu: number;
  queries_per_sec_radeon: number;
  queries_per_sec_cpu: number;
  gpu_mem_util_pct: number;
  p95_query_latency_ms: number;
}

export interface MetricsState {
  byNode: Record<string, MetricsSample[]>;
  connected: boolean;
}

type MAction =
  | { type: "connected" }
  | { type: "disconnected" }
  | { type: "sample"; sample: MetricsSample };

function reducer(s: MetricsState, a: MAction): MetricsState {
  switch (a.type) {
    case "connected": return { ...s, connected: true };
    case "disconnected": return { ...s, connected: false };
    case "sample": {
      const list = [...(s.byNode[a.sample.node] ?? []), a.sample].slice(-60);
      return { ...s, byNode: { ...s.byNode, [a.sample.node]: list } };
    }
  }
}

export function useBrokerMetrics(url: string): MetricsState {
  const [state, dispatch] = useReducer(reducer, { byNode: {}, connected: false });
  useEffect(() => {
    const ws = new WebSocket(url);
    ws.onopen = () => dispatch({ type: "connected" });
    ws.onclose = () => dispatch({ type: "disconnected" });
    ws.onmessage = (ev: MessageEvent) => {
      try {
        const env = JSON.parse(ev.data);
        if (env.type === "metrics") dispatch({ type: "sample", sample: env.payload });
      } catch { /* ignore */ }
    };
    return () => ws.close();
  }, [url]);
  return state;
}
