import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { AttackMatrix } from "../src/views/AttackMatrix";

describe("AttackMatrix", () => {
  it("renders 210 technique cells and lights up orange on first finding", () => {
    const counts: Record<string, number> = { "T1059.001": 1, T1078: 3 };
    render(<AttackMatrix counts={counts} articlesFor={() => [{ id: "a1", content: "x" }]} />);
    const cells = screen.getAllByTestId("attack-cell");
    expect(cells.length).toBe(210);
    const target = document.querySelector('[data-attack-id="T1059.001"]') as HTMLElement;
    const many = document.querySelector('[data-attack-id="T1078"]') as HTMLElement;
    expect(target.className).toContain("bg-orange-500");
    expect(many.className).toContain("bg-red-500");
  });

  it("clicking a cell opens the article list", () => {
    const articlesFor = (id: string) => [{ id: "a1", content: `Finding ${id}` }];
    const { container } = render(<AttackMatrix counts={{ "T1059.001": 1 }} articlesFor={articlesFor} />);
    const cell = container.querySelector('[data-attack-id="T1059.001"]') as HTMLElement;
    act(() => { cell.click(); });
    expect(container.textContent).toContain("Finding T1059.001");
  });
});
