import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ScopeFilter } from "../src/views/ScopeFilter";

describe("ScopeFilter", () => {
  it("redacts rows whose scope is not selected", () => {
    const articles = [
      { id: "a1", type: "finding", content: "public one", scope: "public" },
      { id: "a2", type: "insight", content: "private one", scope: "private" },
    ];
    render(<ScopeFilter articles={articles} />);
    const toggles = screen.getAllByTestId("scope-toggle");
    fireEvent.click(toggles[0]); // deselect private
    expect(screen.getByText("public one")).toBeTruthy();
    expect(screen.getByText("out-of-scope")).toBeTruthy();
  });
});
