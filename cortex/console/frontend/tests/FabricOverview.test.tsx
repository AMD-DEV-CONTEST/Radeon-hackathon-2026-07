import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FabricOverview } from "../src/views/FabricOverview";

describe("FabricOverview", () => {
  it("adds animation class on article.published event with cross-tenant route", () => {
    const events = [
      { event: "article.published", data: { article: { id: "a1", type: "finding" }, route: { from: "soc-alpha", to: "soc-beta" } } },
    ];
    render(<FabricOverview tenants={[{ slug: "soc-alpha" }, { slug: "soc-beta" }]} events={events} />);
    const flow = document.querySelector("[data-flow]");
    expect(flow?.className).toContain("animate-pulse");
  });
});
