import {
  act,
  render,
  screen,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { mockActivationResponse } from "../features/activation/mock/mockActivationResponse";
import {
  PREFERENCES_STORAGE_KEY,
} from "../preferences/preferences";

const fetchSpy = vi.fn();
vi.stubGlobal("fetch", fetchSpy);

// Import after installing fetch so the production HTTP singletons capture
// the browser boundary supplied by this test.
const { App } = await import("./App");

const eventId = "event_0123456789abcdef0123456789abcdef";
const event = {
  id: eventId,
  type: "device_not_shutdown",
  status: "PENDING_HUMAN_REVIEW",
  timestamp: "2026-07-30T10:35:00+08:00",
  severity: "HIGH",
  location: "B03",
  asset_id: "B03-AIRCON",
  description: "Cooling performance is weaker than normal.",
  responsibility: {
    id: "equipment-maintenance",
    name: "Equipment Maintenance",
  },
} as const;
const employee = {
  id: "equipment-maintenance",
  name: "Equipment Maintenance Agent",
  status: "working",
  current_event_id: eventId,
  responsibility: "Equipment anomaly analysis",
  skills: [{ name: "Anomaly analysis" }],
} as const;
const pulse = {
  level: "attention",
  title: "Equipment exception requires review",
  event_id: eventId,
} as const;

describe("F03-D2 Runtime Projection application integration", () => {
  beforeEach(() => {
    fetchSpy.mockReset();
    window.history.replaceState({}, "", "/");
    window.localStorage.clear();
    window.localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        locale: "en-US",
        theme: "dark",
        motion: "reduced",
      }),
    );
  });

  it("refreshes persisted runtime projections when navigating back to Workspace", async () => {
    const user = userEvent.setup();
    let active = false;
    const refreshGate = deferred();
    fetchSpy.mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = requestUrl(input);
        const method = init?.method ?? "GET";

        if (url === "/api/demo/events" && method === "POST") {
          active = true;
          return jsonResponse(mockActivationResponse);
        }
        if (
          active &&
          (url === "/api/workspace" ||
            url === "/api/pulse" ||
            url === "/api/digital-employees")
        ) {
          await refreshGate.promise;
        }
        if (url === "/api/workspace") {
          return jsonResponse(workspacePayload(active));
        }
        if (url === "/api/pulse") {
          return jsonResponse(active ? pulse : null);
        }
        if (url === "/api/digital-employees") {
          return jsonResponse(active ? [employee] : []);
        }
        if (url === "/api/runtime") {
          return jsonResponse(runtimeStatusPayload());
        }
        if (url === "/api/events") {
          return jsonResponse(active ? [event] : []);
        }
        throw new Error(`Unexpected request: ${method} ${url}`);
      },
    );
    render(<App />);

    expect(
      await screen.findByText(
        "No abnormal events are currently projected.",
      ),
    ).toBeInTheDocument();
    expect(requestCount("GET", "/api/workspace")).toBe(1);
    expect(requestCount("GET", "/api/pulse")).toBe(1);
    expect(requestCount("GET", "/api/digital-employees")).toBe(1);

    expect(
      screen.queryByRole("button", {
        name: "Simulate equipment anomaly",
      }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Events" }));
    await screen.findByRole("heading", { name: "Events" });
    active = true;
    await user.click(screen.getByRole("link", { name: "Workspace" }));
    await act(async () => refreshGate.resolve());

    expect(
      await screen.findByRole("button", {
        name: "Open action context: device_not_shutdown",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Open Noah Pulse summary",
      }),
    ).toHaveTextContent("Equipment exception requires review");
    expect(requestCount("GET", "/api/workspace")).toBe(3);
    expect(requestCount("GET", "/api/pulse")).toBe(3);
    expect(requestCount("GET", "/api/digital-employees")).toBe(3);
  });

  it("shows HTTP errors without falling back to any Mock projection", async () => {
    fetchSpy.mockResolvedValue(
      new Response(JSON.stringify({ error_code: "unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const user = userEvent.setup();

    render(<App />);

    expect(
      await screen.findByText("Runtime workspace unavailable."),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Interface status"),
    ).toHaveTextContent("Runtime read unavailable");
    expect(
      screen.queryByText("Cooling loop variance is trending upward"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Detected cooling loop deviation"),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("link", { name: "Digital Employees" }),
    );
    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent("Digital employee collection unavailable");
    expect(
      screen.queryByText("Equipment Maintenance Agent"),
    ).not.toBeInTheDocument();
  });
});

function workspacePayload(active: boolean) {
  return {
    version: "workspace-v1",
    events: active ? [event] : [],
    active_event: active ? event : null,
    pulse: active ? pulse : null,
    employees: active ? [employee] : [],
  };
}

function runtimeStatusPayload() {
  return {
    version: "runtime-status-v1",
    status: "ready",
    provider: "ollama",
    model: "qwen3.5:9b",
    execution: "local",
    selection_source: "environment",
    health: "healthy",
  };
}

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") {
    return input;
  }
  return input instanceof URL ? input.pathname : new URL(input.url).pathname;
}

function requestCount(method: string, url: string): number {
  return fetchSpy.mock.calls.filter(([input, init]) => {
    return (
      requestUrl(input as RequestInfo | URL) === url &&
      ((init as RequestInit | undefined)?.method ?? "GET") === method
    );
  }).length;
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}
