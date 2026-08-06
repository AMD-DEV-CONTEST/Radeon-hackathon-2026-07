import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { WorkflowPage } from "./WorkflowPage";

function response(ok: boolean, body: object): Response {
  return {
    ok,
    json: async () => body,
  } as Response;
}

function renderEvents() {
  return render(
    <MemoryRouter initialEntries={["/events"]}>
      <Routes>
        <Route path="/events" element={<WorkflowPage />} />
        <Route path="/events/:id" element={<p>Event route reached</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("bounded equipment fault Event creation", () => {
  it("starts empty with the bounded editable-location troubleshooting context", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response(true, { events: [] })),
    );

    renderEvents();

    expect(screen.getByLabelText("位置")).toHaveValue("A08");
    expect(screen.getByLabelText("异常描述")).toHaveValue("");
    expect(screen.getByLabelText("异常描述")).toHaveAttribute(
      "placeholder",
      "Describe the observed air-conditioner anomaly.",
    );
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/events", undefined));
  });

  it("shows API creation errors and does not navigate", async () => {
    const fetchMock = vi.fn().mockImplementation(
      (path: string, init?: RequestInit) => {
        if (path === "/api/events" && init?.method === "POST") {
          return Promise.resolve(
            response(false, {
              message:
                "Description must report an observed air-conditioner fault or anomaly.",
            }),
          );
        }
        return Promise.resolve(response(true, { events: [] }));
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderEvents();

    await user.type(screen.getByLabelText("异常描述"), "Write me a poem.");
    await user.click(screen.getByRole("button", { name: "创建 Event" }));

    expect(
      await screen.findByText(
        "Description must report an observed air-conditioner fault or anomaly.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Event route reached")).not.toBeInTheDocument();
  });

  it("submits the exact description and navigates after success", async () => {
    const location = "Workshop-A";
    const description = "The air conditioner is leaking water.";
    const fetchMock = vi.fn().mockImplementation(
      (path: string, init?: RequestInit) => {
        if (path === "/api/events" && init?.method === "POST") {
          return Promise.resolve(
            response(true, { event_id: "event_123", status: "NEW" }),
          );
        }
        return Promise.resolve(response(true, { events: [] }));
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderEvents();

    await user.clear(screen.getByLabelText("位置"));
    await user.type(screen.getByLabelText("位置"), location);
    await user.type(screen.getByLabelText("异常描述"), description);
    await user.click(screen.getByRole("button", { name: "创建 Event" }));

    expect(await screen.findByText("Event route reached")).toBeInTheDocument();
    const postCall = fetchMock.mock.calls.find(
      ([path, init]) =>
        path === "/api/events" && (init as RequestInit | undefined)?.method === "POST",
    );
    expect(postCall).toBeDefined();
    expect(JSON.parse((postCall?.[1] as RequestInit).body as string)).toEqual({
      location,
      asset_type: "air_conditioner",
      description,
    });
  });
});
