import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { ArticleFeed } from "../src/views/ArticleFeed";

function article(id: string, content: string) {
  return { id, type: "finding" as const, content, trust_score: 0.9 };
}

describe("ArticleFeed", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders articles in order with type chips", () => {
    const { container } = render(<ArticleFeed articles={[article("a1", "Alpha"), article("a2", "Beta")]} />);
    expect(screen.getByText("Alpha")).toBeTruthy();
    expect(screen.getByText("Beta")).toBeTruthy();
    expect(screen.getAllByText("finding")).toHaveLength(2);
    expect(container.textContent!.indexOf("Alpha")).toBeLessThan(container.textContent!.indexOf("Beta"));
  });

  it("paginates with a Load more button that appends the next batch", () => {
    const articles = [1, 2, 3, 4].map((n) => article(`a${n}`, `Article ${n}`));
    render(<ArticleFeed articles={articles} pageSize={2} />);

    expect(screen.getByText("Article 1")).toBeTruthy();
    expect(screen.getByText("Article 2")).toBeTruthy();
    expect(screen.queryByText("Article 3")).toBeNull();

    const button = screen.getByRole("button", { name: /Load more/i });
    expect(button.textContent).toContain("2 more");

    fireEvent.click(button);

    expect(screen.getByText("Article 3")).toBeTruthy();
    expect(screen.getByText("Article 4")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Load more/i })).toBeNull();
  });

  it("shows a connecting message until the initial burst settles, then the empty state", () => {
    vi.useFakeTimers();
    render(<ArticleFeed articles={[]} connected={true} />);
    expect(screen.getByText("Connecting to broker…")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(screen.getByText("No articles yet.")).toBeTruthy();
  });

  it("keeps showing the connecting message while disconnected", () => {
    render(<ArticleFeed articles={[]} connected={false} />);
    expect(screen.getByText("Connecting to broker…")).toBeTruthy();
  });
});
