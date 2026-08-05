import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SettingsProvider } from "../SettingsContext";
import { AiRouterProvider, useAiRouter } from "../AiRouterContext";

function TestComponent() {
  const { selectedModel, allowedOptions, routeWarnings } = useAiRouter();
  return (
    <div>
      <span data-testid="selected-model">{selectedModel}</span>
      <span data-testid="allowed-count">{allowedOptions.length}</span>
      <span data-testid="warnings-count">{routeWarnings.length}</span>
    </div>
  );
}

describe("AiRouterContext", () => {
  it("provides active router options and responds to policy context", () => {
    render(
      <SettingsProvider>
        <AiRouterProvider>
          <TestComponent />
        </AiRouterProvider>
      </SettingsProvider>
    );

    expect(screen.getByTestId("selected-model")).toHaveTextContent("auto");
    expect(Number(screen.getByTestId("allowed-count").textContent)).toBeGreaterThan(0);
  });
});
