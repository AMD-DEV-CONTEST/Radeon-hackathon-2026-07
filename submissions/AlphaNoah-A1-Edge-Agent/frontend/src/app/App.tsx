import { MotionConfig } from "motion/react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import {
  ActivationProvider,
  type ActivationDataSource,
} from "../features/activation";
import { httpActivationDataSource } from "../features/activation/composition";
import {
  DigitalEmployeeDetailPage,
  type DigitalEmployeeDataSource,
  DigitalEmployeeListPage,
  DigitalEmployeeProvider,
} from "../features/digital-employees";
import {
  httpDigitalEmployeeDataSource,
} from "../features/digital-employees/composition";
import {
  HumanReviewProvider,
  type HumanReviewDataSource,
} from "../features/human-review";
import { httpHumanReviewDataSource } from "../features/human-review/composition";
import {
  PulseProvider,
  ProviderRuntimeStatusProvider,
  type ProviderRuntimeDataSource,
  type PulseDataSource,
  type WorkspaceDataSource,
  WorkspaceProvider,
} from "../features/runtime";
import {
  httpPulseDataSource,
  httpProviderRuntimeDataSource,
  httpWorkspaceDataSource,
} from "../features/runtime/composition";
import { I18nProvider } from "../i18n/I18nContext";
import { AppShell } from "../layouts/AppShell";
import {
  PreferencesProvider,
  usePreferences,
} from "../preferences/PreferencesContext";
import { RuntimeProjectionRefreshBridge } from "./RuntimeProjectionRefreshBridge";
import { WorkspacePage } from "./WorkspacePage";
import { SettingsPage, WorkflowPage } from "./WorkflowPage";

export interface AppProps {
  activationDataSource?: ActivationDataSource;
  digitalEmployeeDataSource?: DigitalEmployeeDataSource;
  humanReviewDataSource?: HumanReviewDataSource;
  pulseDataSource?: PulseDataSource;
  providerRuntimeDataSource?: ProviderRuntimeDataSource;
  workspaceDataSource?: WorkspaceDataSource;
}

export function App({
  activationDataSource = httpActivationDataSource,
  digitalEmployeeDataSource = httpDigitalEmployeeDataSource,
  humanReviewDataSource = httpHumanReviewDataSource,
  pulseDataSource = httpPulseDataSource,
  providerRuntimeDataSource = httpProviderRuntimeDataSource,
  workspaceDataSource = httpWorkspaceDataSource,
}: AppProps = {}) {
  return (
    <PreferencesProvider>
      <I18nProvider>
        <WorkspaceProvider dataSource={workspaceDataSource}>
          <ProviderRuntimeStatusProvider
            dataSource={providerRuntimeDataSource}
          >
            <PulseProvider dataSource={pulseDataSource}>
              <ActivationProvider dataSource={activationDataSource}>
                <HumanReviewProvider dataSource={humanReviewDataSource}>
                  <DigitalEmployeeProvider
                    dataSource={digitalEmployeeDataSource}
                  >
                    <RuntimeProjectionRefreshBridge />
                    <AppRoutes />
                  </DigitalEmployeeProvider>
                </HumanReviewProvider>
              </ActivationProvider>
            </PulseProvider>
          </ProviderRuntimeStatusProvider>
        </WorkspaceProvider>
      </I18nProvider>
    </PreferencesProvider>
  );
}

function AppRoutes() {
  const {
    preferences: { motion },
  } = usePreferences();

  return (
    <MotionConfig reducedMotion={motion === "reduced" ? "always" : "never"}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<WorkspacePage />} />
            <Route path="events" element={<WorkflowPage />} />
            <Route path="events/:id" element={<WorkflowPage />} />
            <Route path="tasks" element={<WorkflowPage tasksOnly />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route
              path="employees"
              element={<DigitalEmployeeListPage />}
            />
            <Route
              path="employees/:id"
              element={<DigitalEmployeeDetailPage />}
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </MotionConfig>
  );
}
