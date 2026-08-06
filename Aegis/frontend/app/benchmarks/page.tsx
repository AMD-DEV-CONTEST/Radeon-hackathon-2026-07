"use client";

import { useEffect, useState } from "react";
import { api, BenchmarkReport } from "@/lib/api";

export default function BenchmarksPage() {
  const [report, setReport] = useState<BenchmarkReport | null>(null);
  const [reason, setReason] = useState<string | null>(null);

  useEffect(() => {
    api
      .latestBenchmark()
      .then((res) => {
        if (res.available && res.report) setReport(res.report);
        else setReason(res.reason ?? "No benchmark data available.");
      })
      .catch(() => setReason("Couldn't reach the Aegis backend."));
  }, []);

  const maxTokensPerSecond = report
    ? Math.max(...report.runs.map((r) => r.aggregate_tokens_per_second))
    : 0;

  return (
    <div className="detail" style={{ gridColumn: "1 / -1" }}>
      <div className="detail-header">
        <h1>GPU benchmark report</h1>
        <p style={{ color: "var(--text-secondary)", fontSize: 14, maxWidth: 720 }}>
          Tokens/sec, latency, and AMD ROCm GPU utilization across concurrency levels,
          produced by <code style={{ fontFamily: "var(--font-mono)" }}>benchmarks/benchmark_inference.py</code>.
        </p>
      </div>

      {reason && <div className="empty-state" style={{ marginTop: 24 }}>{reason}</div>}

      {report && (
        <>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-tertiary)", margin: "20px 0" }}>
            model={report.model} · generated {new Date(report.generated_at).toLocaleString()}
          </div>

          <div className="evidence-grid">
            {report.runs.map((run) => (
              <div className="evidence-card" key={run.concurrency} style={{ padding: "16px 20px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <div className="evidence-type">concurrency = {run.concurrency}</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--signal)" }}>
                    {run.aggregate_tokens_per_second.toFixed(1)} tok/s aggregate
                  </div>
                </div>

                <div className="confidence-bar-track" style={{ marginTop: 10 }}>
                  <div
                    className="confidence-bar-fill"
                    style={{
                      width: `${(run.aggregate_tokens_per_second / (maxTokensPerSecond || 1)) * 100}%`,
                    }}
                  />
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(4, 1fr)",
                    gap: 12,
                    marginTop: 14,
                    fontFamily: "var(--font-mono)",
                    fontSize: 12,
                    color: "var(--text-secondary)",
                  }}
                >
                  <div>p50 latency: {run.per_request_latency_ms.p50}ms</div>
                  <div>p95 latency: {run.per_request_latency_ms.p95}ms</div>
                  <div>
                    GPU util:{" "}
                    {run.gpu_metrics_available ? `${run.gpu_utilization_pct}%` : "n/a (rocm-smi unavailable)"}
                  </div>
                  <div>
                    VRAM:{" "}
                    {run.gpu_metrics_available ? `${run.gpu_vram_used_pct}%` : "n/a"}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
