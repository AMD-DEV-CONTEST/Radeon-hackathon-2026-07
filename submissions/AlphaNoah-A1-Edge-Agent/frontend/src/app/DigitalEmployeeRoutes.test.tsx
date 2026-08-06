import {
  act,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import {
  mockDigitalEmployeeDataSource,
} from "../features/digital-employees/composition";
import {
  mockPulseDataSource,
  mockProviderRuntimeDataSource,
  mockWorkspaceDataSource,
} from "../features/runtime/composition";
import { App } from "./App";
import {
  PREFERENCES_STORAGE_KEY,
  type Preferences,
} from "../preferences/preferences";

function openAt(
  pathname: string,
  preferences: Partial<Preferences> = {},
) {
  const resolved: Preferences = {
    locale: "en-US",
    theme: "dark",
    motion: "reduced",
    ...preferences,
  };
  window.localStorage.setItem(
    PREFERENCES_STORAGE_KEY,
    JSON.stringify(resolved),
  );
  window.history.replaceState({}, "", pathname);
  return render(
    <App
      digitalEmployeeDataSource={mockDigitalEmployeeDataSource}
      pulseDataSource={mockPulseDataSource}
      providerRuntimeDataSource={mockProviderRuntimeDataSource}
      workspaceDataSource={mockWorkspaceDataSource}
    />,
  );
}

describe("Digital Employee routes", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("loads /employees directly, exposes three roles, and marks primary navigation", async () => {
    openAt("/employees");

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Digital Employee Center",
      }),
    ).toBeInTheDocument();
    const employeeNavigation = screen.getByRole("link", {
      name: "Digital Employees",
    });
    expect(employeeNavigation).toHaveAttribute("aria-current", "page");
    expect(
      screen.getByRole("link", { name: "Workspace" }),
    ).not.toHaveAttribute("aria-current");

    expect(
      screen.getByRole("link", {
        name: /Equipment Maintenance Agent/,
      }),
    ).toHaveAttribute(
      "href",
      "/employees/equipment-maintenance",
    );
    expect(
      screen.getByRole("link", {
        name: /Quality Evidence Agent/,
      }),
    ).toHaveAttribute("href", "/employees/quality-evidence");
    expect(
      screen.getByRole("link", {
        name: /Material Flow Agent/,
      }),
    ).toHaveAttribute("href", "/employees/material-flow");
    expect(screen.getByText("3 roles")).toBeInTheDocument();
  });

  it("navigates from roster to the stable equipment-maintenance route and back through browser history", async () => {
    const user = userEvent.setup();
    openAt("/employees");

    await user.click(
      await screen.findByRole("link", {
        name: /Equipment Maintenance Agent/,
      }),
    );
    expect(window.location.pathname).toBe(
      "/employees/equipment-maintenance",
    );
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Equipment Maintenance Agent",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Digital Employees" }),
    ).toHaveAttribute("aria-current", "page");

    await act(async () => {
      window.history.back();
    });
    await waitFor(() =>
      expect(window.location.pathname).toBe("/employees"),
    );
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Digital Employee Center",
      }),
    ).toBeInTheDocument();
  });

  it("loads the equipment-maintenance detail directly in identity-to-timeline order", async () => {
    openAt("/employees/equipment-maintenance");

    const identity = await screen.findByRole("heading", {
      level: 1,
      name: "Equipment Maintenance Agent",
    });
    const responsibilities = screen.getByRole("heading", {
      level: 2,
      name: "Responsibilities",
    });
    const capabilities = screen.getByRole("heading", {
      level: 2,
      name: "Capability modules",
    });
    const work = screen.getByRole("heading", {
      level: 2,
      name: "Current work",
    });
    const records = screen.getByRole("heading", {
      level: 2,
      name: "Recent work record",
    });

    expect(
      identity.compareDocumentPosition(responsibilities) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      responsibilities.compareDocumentPosition(capabilities) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      capabilities.compareDocumentPosition(work) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      work.compareDocumentPosition(records) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    expect(
      screen.getByText("Monitor equipment condition"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Thermal deviation interpretation"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Review sustained cooling-loop variance"),
    ).toBeInTheDocument();
    const metrics = screen.getByText("Handled today").parentElement;
    expect(metrics).toHaveTextContent("7");
    expect(
      screen.getByText("Pending today").parentElement,
    ).toHaveTextContent("2");
  });

  it("shows the feature-level not-found state for an unknown employee ID", async () => {
    openAt("/employees/not-a-real-employee");

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Digital employee not found",
      }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe(
      "/employees/not-a-real-employee",
    );
    expect(
      screen.getByText(
        "This ID is not present in the current data-source collection.",
      ),
    ).toBeInTheDocument();
  });

  it("renders the list in dark zh-CN from stored preferences", async () => {
    openAt("/employees", {
      locale: "zh-CN",
      theme: "dark",
    });

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "数字员工中心",
      }),
    ).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute(
      "data-theme",
      "dark",
    );
    expect(document.documentElement).toHaveAttribute("lang", "zh-CN");
    expect(
      screen.getByRole("link", { name: /设备维护数字员工/ }),
    ).toBeInTheDocument();
  });

  it("renders the detail in light en-US from stored preferences", async () => {
    openAt("/employees/equipment-maintenance", {
      locale: "en-US",
      theme: "light",
    });

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Equipment Maintenance Agent",
      }),
    ).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute(
      "data-theme",
      "light",
    );
    expect(document.documentElement).toHaveAttribute("lang", "en-US");
  });

  it("keeps Runtime Skill internals and conversational controls out of the detail DOM", async () => {
    openAt("/employees/equipment-maintenance");

    await screen.findByRole("heading", {
      level: 1,
      name: "Equipment Maintenance Agent",
    });
    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(
      /cold-holding-monitor|equipment-evidence-review|skill_id|version\s*1\.|analysis[_ -]?instructions|prompt/i,
    );
    expect(
      screen.queryByRole("textbox"),
    ).not.toBeInTheDocument();
    expect(body).not.toMatch(/\bchat\b|\btyping\b|聊天气泡|正在输入/i);

    const records = screen
      .getByRole("heading", { name: "Recent work record" })
      .closest("section");
    expect(records).not.toBeNull();
    if (records) {
      expect(
        within(records).queryByRole("textbox"),
      ).not.toBeInTheDocument();
      expect(records).toHaveTextContent(
        "Human maintenance review requested",
      );
    }
  });

  it("gives each full-row roster link an accessible identity, state, responsibility, and metric summary", async () => {
    openAt("/employees");

    const link = await screen.findByRole("link", {
      name: /Equipment Maintenance Agent/,
    });
    expect(link).toHaveAccessibleName(
      /Equipment Maintenance Agent.*Working.*Monitor equipment condition.*Handled today.*7.*Pending today.*2/i,
    );
  });
});
