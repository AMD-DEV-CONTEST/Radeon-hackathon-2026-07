import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("shows the operational shell and a healthy local API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const path = String(input);
        return Promise.resolve({
          ok: true,
          json: async () =>
            path.endsWith("/api/tasks")
              ? []
              : {
                  status: "ok",
                  service: "policyseal-api",
                  version: "0.1.0",
                  environment: "test",
                  inference: "local",
                },
        });
      }),
    );

    render(<App />);

    expect(screen.getByRole("heading", { name: "Disclosure tasks" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "New task" })).toBeTruthy();
    expect(screen.getByText("Demo Role Switch")).toBeTruthy();
    expect(screen.getByText("Synthetic")).toBeTruthy();
    expect(await screen.findByText("Local API ready")).toBeTruthy();
    expect(screen.queryByPlaceholderText(/ask/i)).toBeNull();
  });
});
