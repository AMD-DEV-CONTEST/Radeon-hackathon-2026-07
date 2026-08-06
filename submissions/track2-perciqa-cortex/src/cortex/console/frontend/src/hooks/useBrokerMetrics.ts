import { useEffect, useReducer, useRef } from "react";

export interface MetricsSample {
  node: string;
  embeds_per_sec_radeon?: number;
  embeds_per_sec_cpu?: number;
  queries_per_sec_radeon?: number;
  queries_per_sec_cpu?: number;
  gpu_mem_util_pct: number;
  p95_query_latency_ms?: number;
  gpu_device_name?: string;
  gpu_sensor_backend?: string;
  hip_version?: string;
  torch_version?: string;
  vram_total_mb?: number;
  vram_used_mb?: number;
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
  const hasSamples = useRef(false);

  useEffect(() => {
    const ws = new WebSocket(url);
    ws.onopen = () => dispatch({ type: "connected" });
    ws.onclose = () => dispatch({ type: "disconnected" });
    ws.onmessage = (ev: MessageEvent) => {
      try {
        const env = JSON.parse(ev.data);
        if (env.type === "metrics") {
          dispatch({ type: "sample", sample: env.payload });
          hasSamples.current = true;
        }
      } catch { /* ignore */ }
    };
    return () => ws.close();
  }, [url]);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;

    const poll = async () => {
      if (hasSamples.current) return;
      try {
        const rocmRes = await fetch("/api/rocm-info").then(r => r.json());

        if (cancelled) return;

        if (rocmRes && rocmRes.mem_util_pct != null) {
          const sample: MetricsSample = {
            node: "soc-alpha",
            gpu_mem_util_pct: rocmRes.mem_util_pct,
            gpu_device_name: rocmRes.device_name,
            gpu_sensor_backend: rocmRes.sensor_backend,
            hip_version: rocmRes.hip_version,
            torch_version: rocmRes.torch_version,
            vram_total_mb: rocmRes.vram_total_mb,
            vram_used_mb: rocmRes.vram_used_mb,
          };
          dispatch({ type: "sample", sample });
          hasSamples.current = true;
        }
      } catch { /* ignore */ }
    };

    interval = setInterval(poll, 5000);
    poll();

    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, []);

  return state;
}
