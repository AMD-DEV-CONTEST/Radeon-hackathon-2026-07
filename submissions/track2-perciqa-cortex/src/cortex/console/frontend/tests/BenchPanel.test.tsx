import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock fetch so /api/rocm-info and /api/llm-info calls don't error in tests
beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    json: async () => ({ rocm_active: false, status: "offline", model: "test-model", endpoint: "" }),
  }));
});

vi.mock("recharts", () => ({
  BarChart: () => <div data-testid="bar-chart" />,
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

import { BenchPanel } from "../src/views/BenchPanel";

describe("BenchPanel", () => {
  it("renders with required props", () => {
    const byNode = {
      "soc-alpha": [{ node: "soc-alpha", embeds_per_sec_radeon: 142, embeds_per_sec_cpu: 18, queries_per_sec_radeon: 0, queries_per_sec_cpu: 0, gpu_mem_util_pct: 86, p95_query_latency_ms: 42 }],
    };
    render(<BenchPanel byNode={byNode} articles={[]} activities={[]} connected={true} />);
    expect(screen.getByText("Bench Panel")).toBeTruthy();
  });
});
