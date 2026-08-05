import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarketplacePanel } from "../MarketplacePanel";
import { SettingsProvider } from "@/contexts/SettingsContext";

describe("MarketplacePanel", () => {
  it("opens an actionable local community hub panel instead of a dead button", () => {
    // MarketplacePanel now reads real keyStatus via useSettings() (LLM
    // marketplace cards show actual "Connected"/"Add API Key" state instead
    // of a hardcoded fake "installed" badge) -- needs a real provider, not a
    // bare render, or useSettings() throws before anything renders.
    render(
      <SettingsProvider>
        <MarketplacePanel />
      </SettingsProvider>
    );

    fireEvent.click(screen.getByTestId("community-hub-button"));

    expect(screen.getByTestId("community-hub-panel")).toHaveTextContent("Add-on Manager");
    expect(screen.getByText(/Public community publishing is not enabled/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Configure providers and API-backed models"));
    expect(screen.getAllByText("LLM Providers").length).toBeGreaterThan(0);
  });
});
