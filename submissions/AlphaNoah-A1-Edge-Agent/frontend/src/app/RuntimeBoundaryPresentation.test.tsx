import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { WorkspaceProvider } from "../features/runtime";
import { HttpWorkspaceDataSource } from "../features/runtime/composition";
import { I18nProvider } from "../i18n/I18nContext";
import { AppShell } from "../layouts/AppShell";
import {
  PREFERENCES_STORAGE_KEY,
} from "../preferences/preferences";
import { PreferencesProvider } from "../preferences/PreferencesContext";
import { WorkspacePage } from "./WorkspacePage";

describe("Runtime boundary presentation", () => {
  it("identifies the unavailable HTTP boundary without exposing Mock copy", async () => {
    window.localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        locale: "en-US",
        theme: "dark",
        motion: "reduced",
      }),
    );

    render(
      <PreferencesProvider>
        <I18nProvider>
          <WorkspaceProvider dataSource={new HttpWorkspaceDataSource()}>
            <MemoryRouter>
              <Routes>
                <Route element={<AppShell />}>
                  <Route index element={<WorkspacePage />} />
                </Route>
              </Routes>
            </MemoryRouter>
          </WorkspaceProvider>
        </I18nProvider>
      </PreferencesProvider>,
    );

    expect(
      await screen.findByText("Runtime workspace unavailable."),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText("Runtime read unavailable"),
    ).not.toHaveLength(0);
    expect(
      screen.getByText("Interface layer · Runtime read boundary"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Mock boundary")).not.toBeInTheDocument();
  });
});
