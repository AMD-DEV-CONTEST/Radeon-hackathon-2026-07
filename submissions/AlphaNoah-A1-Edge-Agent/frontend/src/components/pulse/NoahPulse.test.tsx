import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../../i18n/I18nContext";
import { mockPulseNotice } from "../../mock";
import {
  PREFERENCES_STORAGE_KEY,
  type MotionPreference,
} from "../../preferences/preferences";
import { PreferencesProvider } from "../../preferences/PreferencesContext";
import { NoahPulse } from "./NoahPulse";

function renderPulse({
  motion = "standard",
  withNotice = true,
  loading = false,
  unavailable = false,
  onOpenAction,
}: {
  motion?: MotionPreference;
  withNotice?: boolean;
  loading?: boolean;
  unavailable?: boolean;
  onOpenAction?: (
    activityId: string,
    trigger?: HTMLElement,
  ) => void;
} = {}) {
  window.localStorage.setItem(
    PREFERENCES_STORAGE_KEY,
    JSON.stringify({
      locale: "en-US",
      theme: "dark",
      motion,
    }),
  );

  return render(
    <PreferencesProvider>
      <I18nProvider>
        <NoahPulse
          notice={withNotice ? mockPulseNotice : undefined}
          loading={loading}
          unavailable={unavailable}
          onOpenAction={onOpenAction}
        />
      </I18nProvider>
    </PreferencesProvider>,
  );
}

describe("NoahPulse", () => {
  it("renders an inert, accessible idle capsule when there is no notice", () => {
    const { container } = renderPulse({ withNotice: false });

    const root = container.querySelector("aside");
    const capsule = screen.getByRole("status");

    expect(root).toHaveAttribute("data-state", "idle");
    expect(screen.getByText("Noah Pulse")).toBeInTheDocument();
    expect(screen.getByText("Idle")).toBeInTheDocument();
    expect(capsule).toHaveAttribute("aria-live", "polite");
    expect(
      screen.queryByRole("button", {
        name: "Open Noah Pulse summary",
      }),
    ).not.toBeInTheDocument();
  });

  it("distinguishes an unavailable read from confirmed idle", () => {
    const { container } = renderPulse({
      withNotice: false,
      unavailable: true,
    });

    expect(container.querySelector("aside")).toHaveAttribute(
      "data-state",
      "unavailable",
    );
    expect(
      screen.getByText("Runtime unavailable"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Idle")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Open Noah Pulse summary",
      }),
    ).not.toBeInTheDocument();
  });

  it("labels an in-flight empty read without claiming it is online", () => {
    renderPulse({ withNotice: false, loading: true });

    expect(screen.getByText("Reading Runtime")).toBeInTheDocument();
    expect(screen.queryByText("Online")).not.toBeInTheDocument();
  });

  it("exposes the attention state and structured region semantics", async () => {
    const user = userEvent.setup();
    const { container } = renderPulse();
    const capsule = screen.getByRole("button", {
      name: "Open Noah Pulse summary",
    });

    expect(container.querySelector("aside")).toHaveAttribute(
      "data-state",
      "attention",
    );
    expect(capsule).toHaveAttribute("aria-expanded", "false");
    expect(capsule).toHaveAttribute(
      "aria-controls",
      "noah-pulse-expanded",
    );
    expect(capsule).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.getByText("Review needed")).toBeInTheDocument();

    await user.click(capsule);

    const region = await screen.findByRole("dialog", {
      name: "Noah Pulse event context",
    });
    expect(region).toHaveAttribute("id", "noah-pulse-expanded");
    expect(region).toHaveAttribute("aria-modal", "false");
    expect(
      screen.getByRole("heading", {
        name: "Cooling loop variance detected",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Facts")).toBeInTheDocument();
    expect(screen.getByText("AI")).toBeInTheDocument();
    expect(screen.getByText("Next")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Close Noah Pulse summary",
      }),
    ).toHaveFocus();
  });

  it("closes with Escape and restores focus to the capsule", async () => {
    const user = userEvent.setup();
    renderPulse();
    await user.click(
      screen.getByRole("button", {
        name: "Open Noah Pulse summary",
      }),
    );
    await screen.findByRole("dialog", {
      name: "Noah Pulse event context",
    });
    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", {
          name: "Noah Pulse event context",
        }),
      ).not.toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Open Noah Pulse summary",
        }),
      ).toHaveFocus(),
    );
  });

  it("closes by button and restores focus to the capsule", async () => {
    const user = userEvent.setup();
    renderPulse();

    await user.click(
      screen.getByRole("button", {
        name: "Open Noah Pulse summary",
      }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "Close Noah Pulse summary",
      }),
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Open Noah Pulse summary",
        }),
      ).toHaveFocus(),
    );
  });

  it("keeps the Pulse operable with reduced motion selected", async () => {
    const user = userEvent.setup();
    renderPulse({ motion: "reduced" });
    const capsule = screen.getByRole("button", {
      name: "Open Noah Pulse summary",
    });

    expect(document.documentElement).toHaveAttribute(
      "data-motion",
      "reduced",
    );
    await user.click(capsule);
    expect(
      await screen.findByRole("dialog", {
        name: "Noah Pulse event context",
      }),
    ).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Open Noah Pulse summary",
        }),
      ).toHaveFocus(),
    );
  });

  it("opens the matching action context without submitting an action", async () => {
    const user = userEvent.setup();
    const onOpenAction = vi.fn();
    renderPulse({ onOpenAction });

    await user.click(
      screen.getByRole("button", {
        name: "Open Noah Pulse summary",
      }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "Open action context",
      }),
    );

    await waitFor(() => expect(onOpenAction).toHaveBeenCalledTimes(1));
    expect(onOpenAction).toHaveBeenCalledWith(
      mockPulseNotice.activityId,
      expect.any(HTMLElement),
    );
    expect(
      screen.queryByRole("dialog", {
        name: "Noah Pulse event context",
      }),
    ).not.toBeInTheDocument();
    expect(onOpenAction.mock.calls[0]?.[1]).toBe(
      screen.getByRole("button", {
        name: "Open Noah Pulse summary",
      }),
    );
  });
});
