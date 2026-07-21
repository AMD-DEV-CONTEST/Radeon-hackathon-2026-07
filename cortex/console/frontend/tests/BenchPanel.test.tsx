import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

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
  it("renders two bar charts and updates on new samples", () => {
    const byNode = {
      "soc-alpha": [{ node: "soc-alpha", embeds_per_sec_radeon: 142, embeds_per_sec_cpu: 18, queries_per_sec_radeon: 0, queries_per_sec_cpu: 0, gpu_mem_util_pct: 86, p95_query_latency_ms: 42 }],
    };
    render(<BenchPanel byNode={byNode} />);
    expect(screen.getAllByTestId("bar-chart").length).toBe(2);
  });
});
