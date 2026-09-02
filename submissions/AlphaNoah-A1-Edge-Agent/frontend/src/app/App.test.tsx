import {
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  mockDigitalEmployeeDataSource,
} from "../features/digital-employees/composition";
import {
  mockPulseDataSource,
  mockProviderRuntimeDataSource,
  mockWorkspaceDataSource,
} from "../features/runtime/composition";
import {
  PREFERENCES_STORAGE_KEY,
  type Locale,
  type MotionPreference,
  type ThemePreference,
} from "../preferences/preferences";
import { App } from "./App";

function usePreferences({
  locale = "zh-CN",
  theme = "dark",
  motion = "standard",
}: {
  locale?: Locale;
  theme?: ThemePreference;
  motion?: MotionPreference;
} = {}) {
  window.localStorage.setItem(
    PREFERENCES_STORAGE_KEY,
    JSON.stringify({
      locale,
      theme,
      motion,
    }),
  );
}

function renderMockApp() {
  return render(
    <App
      digitalEmployeeDataSource={mockDigitalEmployeeDataSource}
      pulseDataSource={mockPulseDataSource}
      providerRuntimeDataSource={mockProviderRuntimeDataSource}
      workspaceDataSource={mockWorkspaceDataSource}
    />,
  );
}

describe("F02.6 polished agent workspace", () => {
  it("leads with field context, opens action context, and keeps commands local", async () => {
    usePreferences();
    const user = userEvent.setup();
    renderMockApp();

    expect(
      screen.getByRole("heading", {
        name: "北区装配 · 3 号线",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("先理解现场，再决定行动。"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "当前活动" }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 个事件需要关注")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    const eventTrigger = screen.getByRole("button", {
        name: /换料流程进入验证节点/,
      });
    await user.click(eventTrigger);
    expect(
      screen.getByRole("dialog", {
        name: "换料流程进入验证节点",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("保持流程暂停；F02 不提供确认操作。"),
    ).toBeInTheDocument();
    expect(screen.getByText("人工决定")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "关闭行动上下文" }),
    );
    await waitFor(() => expect(eventTrigger).toHaveFocus());

    await user.click(
      screen.getByRole("button", { name: "总结当前信号" }),
    );
    await user.click(
      screen.getByRole("button", { name: "暂存指令" }),
    );
    expect(
      screen.getByText(
        "指令已在本地暂存，没有向 Runtime 发出请求。",
      ),
    ).toBeInTheDocument();
  });

  it("operates preferences, persists them, and closes with Escape", async () => {
    usePreferences();
    const user = userEvent.setup();
    renderMockApp();

    const trigger = screen.getByRole("button", {
      name: "打开偏好设置",
    });
    await user.click(trigger);
    expect(
      screen.getByRole("dialog", { name: "偏好设置" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "关闭偏好设置" }),
    ).toHaveFocus();

    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(
      screen.getByRole("button", { name: "刷新检测" }),
    ).toHaveFocus();

    await user.click(screen.getByLabelText("English"));
    expect(
      screen.getByRole("heading", {
        name: "North assembly · Line 3",
      }),
    ).toBeInTheDocument();

    await user.click(screen.getByLabelText("Light"));
    await user.click(screen.getByLabelText("Reduced"));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(document.documentElement).toHaveAttribute(
      "data-motion",
      "reduced",
    );

    await waitFor(() => {
      expect(
        JSON.parse(
          window.localStorage.getItem(PREFERENCES_STORAGE_KEY) ?? "{}",
        ),
      ).toEqual({
        locale: "en-US",
        theme: "light",
        motion: "reduced",
      });
    });

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("morphs Noah Pulse into structured context and opens the action panel", async () => {
    usePreferences();
    const user = userEvent.setup();
    renderMockApp();

    const pulse = screen.getByRole("button", {
      name: "打开 Noah Pulse 摘要",
    });
    expect(pulse).toHaveAttribute("aria-expanded", "false");

    await user.click(pulse);
    expect(
      await screen.findByRole("dialog", {
        name: "Noah Pulse 事件上下文",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("AI 理解")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "打开行动上下文" }),
    );
    expect(
      await screen.findByRole("dialog", {
        name: "冷却回路偏差持续上升",
      }),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "关闭行动上下文" }),
    );

    await waitFor(() =>
      expect(
        screen.queryByText(
          "冷却回路偏移仍在范围内，但持续时间已值得复核。",
        ),
      ).not.toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "打开 Noah Pulse 摘要",
        }),
      ).toHaveFocus(),
    );
  });

  it("closes the action panel with Escape and restores event focus", async () => {
    usePreferences();
    const user = userEvent.setup();
    renderMockApp();

    const eventTrigger = screen.getByRole("button", {
      name: /冷却回路偏差持续上升/,
    });
    await user.click(eventTrigger);
    expect(
      screen.getByRole("button", { name: "关闭行动上下文" }),
    ).toHaveFocus();

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", {
          name: "冷却回路偏差持续上升",
        }),
      ).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(eventTrigger).toHaveFocus());
  });

  it("closes preferences only when the backdrop itself is pressed", async () => {
    usePreferences();
    const user = userEvent.setup();
    renderMockApp();

    const trigger = screen.getByRole("button", {
      name: "打开偏好设置",
    });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "偏好设置" });

    fireEvent.mouseDown(dialog);
    expect(dialog).toBeInTheDocument();

    const backdrop = dialog.parentElement;
    expect(backdrop).not.toBeNull();
    if (backdrop) {
      fireEvent.mouseDown(backdrop);
    }
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("renders all four event rows and updates selection for mouse and keyboard activation", async () => {
    usePreferences({ locale: "en-US" });
    const user = userEvent.setup();
    renderMockApp();

    const events = [
      {
        title: "Cooling loop variance is trending upward",
        lifecycle: "Event lifecycle: Analyzing",
      },
      {
        title: "Inspection evidence package completed",
        lifecycle: "Event lifecycle: Evidence",
      },
      {
        title: "Material changeover entered verification",
        lifecycle: "Event lifecycle: Human review",
      },
      {
        title: "Edge node heartbeat recovered",
        lifecycle: "Event lifecycle: Closed",
      },
    ];
    const triggers = events.map(({ title }) =>
      screen.getByRole("button", {
        name: `Open action context: ${title}`,
      }),
    );

    expect(triggers).toHaveLength(4);
    for (const trigger of triggers) {
      expect(trigger).toHaveAttribute("data-selected", "false");
      expect(trigger).toHaveAttribute("aria-pressed", "false");
    }
    events.forEach(({ lifecycle }, index) => {
      expect(
        within(triggers[index] as HTMLElement).getByLabelText(
          lifecycle,
        ),
      ).toBeInTheDocument();
    });

    for (const [index, { title }] of events.entries()) {
      const trigger = triggers[index] as HTMLButtonElement;
      trigger.focus();
      expect(trigger).toHaveFocus();

      if (index === events.length - 1) {
        await user.keyboard("{Enter}");
      } else {
        await user.click(trigger);
      }

      expect(trigger).toHaveAttribute("data-selected", "true");
      expect(trigger).toHaveAttribute("aria-pressed", "true");
      expect(
        screen.getByRole("dialog", { name: title }),
      ).toBeInTheDocument();

      await user.click(
        screen.getByRole("button", {
          name: "Close action context",
        }),
      );
      await waitFor(() =>
        expect(
          screen.queryByRole("dialog", { name: title }),
        ).not.toBeInTheDocument(),
      );
      await waitFor(() => expect(trigger).toHaveFocus());
    }
  });

  it("keeps smart instructions local, accessible, and disabled until input is meaningful", async () => {
    usePreferences({ locale: "en-US", theme: "light" });
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    renderMockApp();

    expect(document.documentElement).toHaveAttribute(
      "data-theme",
      "light",
    );
    expect(document.documentElement).toHaveAttribute("lang", "en-US");

    const input = screen.getByRole("textbox", { name: "Instruction" });
    const submit = screen.getByRole("button", {
      name: "Stage instruction",
    });
    expect(submit).toBeDisabled();

    await user.click(input);
    expect(input).toHaveFocus();
    await user.type(input, "   ");
    expect(submit).toBeDisabled();

    await user.clear(input);
    await user.type(input, "Inspect the active cooling signal");
    expect(submit).toBeEnabled();
    await user.click(submit);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Instruction staged locally. No Runtime request was made.",
    );
    expect(fetchSpy).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole("button", {
        name: "List the current evidence",
      }),
    );
    expect(input).toHaveValue("List the current evidence");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
