import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { App } from "../src/App";

describe("Layout", () => {
  it("renders header, nav tabs, and status pill", () => {
    render(<App />);
    expect(screen.getByText(/Perciqa Cortex/i)).toBeTruthy();
    expect(screen.getByText(/Fabric Overview/i)).toBeTruthy();
    expect(screen.getByText(/Article Feed/i)).toBeTruthy();
    expect(screen.getByText(/Provenance Graph/i)).toBeTruthy();
    expect(screen.getByText(/Bench Panel/i)).toBeTruthy();
    expect(screen.getByText(/Attack Matrix/i)).toBeTruthy();
  });
});
