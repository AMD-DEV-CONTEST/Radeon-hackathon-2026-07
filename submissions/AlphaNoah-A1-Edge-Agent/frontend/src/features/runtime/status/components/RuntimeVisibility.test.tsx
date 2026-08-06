import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { I18nProvider } from "../../../../i18n/I18nContext";
import {
  PREFERENCES_STORAGE_KEY,
} from "../../../../preferences/preferences";
import { PreferencesProvider } from "../../../../preferences/PreferencesContext";
import {
  ProviderRuntimeReadError,
  type ProviderRuntimeDataSource,
  type ProviderRuntimeRequest,
  type ProviderRuntimeSnapshot,
} from "../models/providerRuntime";
import { ProviderRuntimeStatusProvider } from "../provider/ProviderRuntimeStatusContext";
import { AiRuntimeSetupPanel } from "./AiRuntimeSetupPanel";
import { RuntimeStatusCard } from "./RuntimeStatusCard";

const readySnapshot: ProviderRuntimeSnapshot = {
  source: "mock",
  contractVersion: "runtime-status-v1",
  visibility: "ready",
  runtimeStatus: "ready",
  provider: "ollama",
  model: "qwen3.5:9b",
  execution: "local",
  selectionSource: "saved_config",
  health: "healthy",
};

describe("F04-A Runtime visibility", () => {
  beforeEach(() => {
    window.localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        locale: "en-US",
        theme: "dark",
        motion: "reduced",
      }),
    );
  });

  it("shows the exact ready Provider, model, execution and health", async () => {
    renderRuntime(new StaticDataSource(readySnapshot));

    const card = screen.getByRole("heading", { name: "AI Runtime" })
      .closest("section");
    await waitFor(() =>
      expect(card).toHaveAttribute("data-runtime-state", "ready"),
    );
    expect(screen.getAllByText("Healthy")).not.toHaveLength(0);
    expect(screen.getAllByText("Ollama")).not.toHaveLength(0);
    expect(screen.getAllByText("qwen3.5:9b")).not.toHaveLength(0);
    expect(screen.getAllByText("Local Edge")).not.toHaveLength(0);
  });

  it("shows unconfigured as unavailable without a fake Online state", async () => {
    renderRuntime(
      new StaticDataSource({
        ...readySnapshot,
        visibility: "unavailable",
        runtimeStatus: "unconfigured",
        provider: null,
        model: null,
        execution: "none",
        selectionSource: "none",
        health: "not_configured",
      }),
    );

    const card = screen.getByRole("heading", { name: "AI Runtime" })
      .closest("section");
    await waitFor(() =>
      expect(card).toHaveAttribute("data-runtime-state", "unavailable"),
    );
    expect(screen.getAllByText("Unavailable")).not.toHaveLength(0);
    expect(screen.getByText("Provider not configured.")).toBeInTheDocument();
    expect(screen.queryByText("Online")).not.toBeInTheDocument();
  });

  it("shows unknown when /api/runtime cannot be read", async () => {
    renderRuntime(new FailingDataSource());

    expect(await screen.findByText("Runtime status unavailable."))
      .toBeInTheDocument();
    const card = screen.getByRole("heading", { name: "AI Runtime" })
      .closest("section");
    expect(card).toHaveAttribute("data-runtime-state", "unknown");
    expect(screen.queryByText("Online")).not.toBeInTheDocument();
  });

  it("refreshes only the injected Runtime data source", async () => {
    const dataSource = new StaticDataSource(readySnapshot);
    const user = userEvent.setup();
    renderRuntime(dataSource);
    await waitFor(() => expect(dataSource.reads).toBe(1));

    await user.click(
      screen.getByRole("button", { name: "Refresh detection" }),
    );

    await waitFor(() => expect(dataSource.reads).toBe(2));
    expect(screen.getByText("Not reported by Runtime API"))
      .toBeInTheDocument();
  });
});

function renderRuntime(dataSource: ProviderRuntimeDataSource) {
  return render(
    <PreferencesProvider>
      <I18nProvider>
        <ProviderRuntimeStatusProvider dataSource={dataSource}>
          <RuntimeStatusCard />
          <AiRuntimeSetupPanel />
        </ProviderRuntimeStatusProvider>
      </I18nProvider>
    </PreferencesProvider>,
  );
}

class StaticDataSource implements ProviderRuntimeDataSource {
  readonly source = "mock" as const;
  reads = 0;

  constructor(private readonly snapshot: ProviderRuntimeSnapshot) {}

  getInitialSnapshot(): ProviderRuntimeSnapshot {
    return this.snapshot;
  }

  async getRuntimeStatus(
    request: ProviderRuntimeRequest = {},
  ): Promise<ProviderRuntimeSnapshot> {
    if (request.signal?.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }
    this.reads += 1;
    return this.snapshot;
  }
}

class FailingDataSource implements ProviderRuntimeDataSource {
  readonly source = "mock" as const;

  getInitialSnapshot(): null {
    return null;
  }

  async getRuntimeStatus(): Promise<ProviderRuntimeSnapshot> {
    throw new ProviderRuntimeReadError(
      "transport",
      this.source,
      "offline",
    );
  }
}
