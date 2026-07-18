import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { App } from "../src/App";

describe("App scaffold", () => {
  it("renders the Perciqa Cortex title", () => {
    render(<App />);
    expect(screen.getByText(/Perciqa Cortex/i)).toBeTruthy();
  });
});
