import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ArticleDetail } from "../src/views/ArticleDetail";

vi.mock("../src/hooks/useBrokerEvents", () => ({ useBrokerEvents: () => ({}) }));

describe("ArticleDetail", () => {
  it("renders content, payload, signature, provenance tree", async () => {
    const article = {
      id: "a1", type: "finding", content: "T1059.001 observed",
      payload: { attack_id: "T1059.001", severity: "high" },
      trust_score: 0.85,
      cites: ["c1", "c2"],
      agent_signature: "sig",
      org_signature: "cosig",
      provenance_children: [{ id: "c1", content: "Cited one" }, { id: "c2", content: "Cited two" }],
    };
    render(<ArticleDetail articleId="a1" fetchArticle={async () => article} />);
    await waitFor(() => expect(screen.getByText(/T1059.001 observed/i)).toBeTruthy());
    expect(screen.getByText(/"T1059.001"/)).toBeTruthy();
    expect(screen.getByTestId("sig-agent").textContent).toContain("\u2713");
    expect(screen.getByText("Cited one")).toBeTruthy();
    expect(screen.getByText("Cited two")).toBeTruthy();
  });
});
