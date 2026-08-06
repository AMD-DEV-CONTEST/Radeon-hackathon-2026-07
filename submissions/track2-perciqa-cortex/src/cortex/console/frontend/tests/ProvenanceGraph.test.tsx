import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  Network: vi.fn(),
  DataSet: class {
    items: unknown[];
    constructor(items: unknown[]) { this.items = items; }
  },
}));

vi.mock("vis-network", () => ({ default: mocks, Network: mocks.Network, DataSet: mocks.DataSet }));

import { ProvenanceGraph } from "../src/views/ProvenanceGraph";

describe("ProvenanceGraph", () => {
  it("builds nodes and cites edges", () => {
    const articles = [
      { id: "a1", type: "finding", content: "root", trust_score: 0.8, cites: ["a2"] },
      { id: "a2", type: "precedent", content: "cited", trust_score: 0.5 },
    ];
    render(<ProvenanceGraph articles={articles} />);
    expect(mocks.Network).toHaveBeenCalled();
    const call = mocks.Network.mock.calls[0];
    const data = call[1];
    expect(data.nodes.items.length).toBe(2);
    expect(data.edges.items.length).toBe(1);
    expect(data.edges.items[0].from).toBe("a1");
    expect(data.edges.items[0].to).toBe("a2");
  });
});
