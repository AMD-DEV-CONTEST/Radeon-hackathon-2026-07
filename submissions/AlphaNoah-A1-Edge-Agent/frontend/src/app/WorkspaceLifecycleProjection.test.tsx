import { render, screen } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { adaptEventView } from "../features/runtime/adapter/eventViewAdapter";
import {
  literalText,
  type WorkspaceDataSource,
  type WorkspaceSnapshot,
} from "../features/runtime/models";
import { WorkspaceProvider } from "../features/runtime/hooks/WorkspaceProviderContext";
import { buildMockWorkspaceSnapshot } from "../features/runtime/mock/MockWorkspaceDataSource";
import { ProviderRuntimeStatusProvider } from "../features/runtime";
import {
  mockProviderRuntimeDataSource,
} from "../features/runtime/composition";
import { I18nProvider } from "../i18n/I18nContext";
import {
  PREFERENCES_STORAGE_KEY,
} from "../preferences/preferences";
import { PreferencesProvider } from "../preferences/PreferencesContext";
import { WorkspacePage } from "./WorkspacePage";

function eventWithStatus(status: string) {
  return adaptEventView({
    eventId: `event_${status.toLowerCase()}`,
    status,
    severity: "HIGH",
    title: literalText(`${status} event`),
    detail: null,
    sourceLabel: null,
    occurredAt: null,
    occurredLabel: null,
    location: null,
    assetId: null,
    actionSummaryId: null,
  });
}

function renderWorkspace(snapshot: WorkspaceSnapshot) {
  const source: WorkspaceDataSource = {
    source: "mock",
    getInitialSnapshot: () => snapshot,
    getWorkspace: async () => snapshot,
  };
  window.localStorage.setItem(
    PREFERENCES_STORAGE_KEY,
    JSON.stringify({
      locale: "en-US",
      theme: "dark",
      motion: "reduced",
    }),
  );

  return render(
    <PreferencesProvider>
      <I18nProvider>
        <WorkspaceProvider dataSource={source}>
          <ProviderRuntimeStatusProvider
            dataSource={mockProviderRuntimeDataSource}
          >
            <MemoryRouter>
              <Routes>
                <Route
                  element={
                    <Outlet
                      context={{
                        selectedEventId: null,
                        openActionPanel: vi.fn(),
                      }}
                    />
                  }
                >
                  <Route index element={<WorkspacePage />} />
                </Route>
              </Routes>
            </MemoryRouter>
          </ProviderRuntimeStatusProvider>
        </WorkspaceProvider>
      </I18nProvider>
    </PreferencesProvider>,
  );
}

describe("Workspace lifecycle compatibility projection", () => {
  it.each([
    ["FAILED", "FAILED"],
    ["FUTURE_RUNTIME_STATUS", "FUTURE_RUNTIME_STATUS"],
  ])(
    "does not draw %s as a 100%% completed Closed lifecycle",
    (status, visibleLabel) => {
      const base = buildMockWorkspaceSnapshot();
      renderWorkspace({
        ...base,
        events: [eventWithStatus(status)],
        actionSummaries: [],
        currentFocus: null,
      });

      const lifecycle = screen.getByLabelText(
        `Event lifecycle: ${visibleLabel}`,
      );
      expect(lifecycle).not.toHaveTextContent("Closed");
      expect(
        lifecycle.querySelectorAll('[data-complete="true"]'),
      ).not.toHaveLength(6);
    },
  );
});
