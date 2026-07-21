import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ArticleFeed } from "../src/views/ArticleFeed";

describe("ArticleFeed", () => {
  it("renders in reverse-chrono order with type-color classes", () => {
    const articles = [
      { id: "a1", type: "finding", content: "Alpha", trust_score: 0.9 },
      { id: "a2", type: "insight", content: "Beta", trust_score: 0.6 },
    ];
    render(<ArticleFeed articles={articles} />);
    const rows = screen.getAllByTestId("article-row");
    expect(rows[0].textContent).toContain("Alpha");
    expect(rows[0].className).toContain("text-red-500");
    expect(rows[1].textContent).toContain("Beta");
    expect(rows[1].className).toContain("text-blue-500");
  });
});
