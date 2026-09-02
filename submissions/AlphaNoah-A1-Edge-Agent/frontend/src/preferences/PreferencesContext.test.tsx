import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { setMediaQuery } from "../test/setup";
import {
  PreferencesProvider,
  usePreferences,
} from "./PreferencesContext";
import {
  PREFERENCES_STORAGE_KEY,
  readStoredPreferences,
} from "./preferences";

const darkQuery = "(prefers-color-scheme: dark)";
const reducedQuery = "(prefers-reduced-motion: reduce)";

function PreferenceProbe() {
  const {
    preferences,
    resolvedTheme,
    setLocale,
    setMotion,
    setTheme,
  } = usePreferences();

  return (
    <div>
      <output data-testid="locale">{preferences.locale}</output>
      <output data-testid="theme">{preferences.theme}</output>
      <output data-testid="resolved-theme">{resolvedTheme}</output>
      <output data-testid="motion">{preferences.motion}</output>
      <button type="button" onClick={() => setLocale("en-US")}>
        locale-en
      </button>
      <button type="button" onClick={() => setTheme("light")}>
        theme-light
      </button>
      <button type="button" onClick={() => setTheme("system")}>
        theme-system
      </button>
      <button type="button" onClick={() => setMotion("standard")}>
        motion-standard
      </button>
      <button type="button" onClick={() => setMotion("reduced")}>
        motion-reduced
      </button>
    </div>
  );
}

describe("PreferencesProvider", () => {
  it("uses the browser language and reduced-motion preference as defaults", () => {
    Object.defineProperty(window.navigator, "language", {
      configurable: true,
      value: "zh-HK",
    });
    setMediaQuery(reducedQuery, true);

    render(
      <PreferencesProvider>
        <PreferenceProbe />
      </PreferencesProvider>,
    );

    expect(screen.getByTestId("locale")).toHaveTextContent("zh-CN");
    expect(screen.getByTestId("motion")).toHaveTextContent("reduced");
  });

  it("follows system theme changes only while theme is system", async () => {
    setMediaQuery(darkQuery, true);
    render(
      <PreferencesProvider>
        <PreferenceProbe />
      </PreferencesProvider>,
    );

    expect(screen.getByTestId("theme")).toHaveTextContent("system");
    expect(screen.getByTestId("resolved-theme")).toHaveTextContent("dark");

    act(() => setMediaQuery(darkQuery, false));
    expect(screen.getByTestId("resolved-theme")).toHaveTextContent("light");

    await userEvent.click(screen.getByText("theme-light"));
    act(() => setMediaQuery(darkQuery, true));
    expect(screen.getByTestId("resolved-theme")).toHaveTextContent("light");
  });

  it("persists the system preference while its resolved theme changes", async () => {
    setMediaQuery(darkQuery, false);
    const user = userEvent.setup();
    render(
      <PreferencesProvider>
        <PreferenceProbe />
      </PreferencesProvider>,
    );

    await user.click(screen.getByText("theme-light"));
    await user.click(screen.getByText("theme-system"));
    expect(document.documentElement).toHaveAttribute(
      "data-theme-preference",
      "system",
    );
    expect(document.documentElement).toHaveAttribute(
      "data-theme",
      "light",
    );

    act(() => setMediaQuery(darkQuery, true));
    expect(document.documentElement).toHaveAttribute(
      "data-theme",
      "dark",
    );
    await waitFor(() =>
      expect(
        JSON.parse(
          window.localStorage.getItem(PREFERENCES_STORAGE_KEY) ?? "{}",
        ).theme,
      ).toBe("system"),
    );
  });

  it("restores validated preferences and persists manual updates", async () => {
    setMediaQuery(reducedQuery, true);
    window.localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        locale: "zh-CN",
        theme: "dark",
        motion: "reduced",
      }),
    );
    const user = userEvent.setup();

    render(
      <PreferencesProvider>
        <PreferenceProbe />
      </PreferencesProvider>,
    );

    expect(screen.getByTestId("locale")).toHaveTextContent("zh-CN");
    expect(screen.getByTestId("resolved-theme")).toHaveTextContent("dark");
    expect(screen.getByTestId("motion")).toHaveTextContent("reduced");

    await user.click(screen.getByText("locale-en"));
    await user.click(screen.getByText("motion-standard"));

    await waitFor(() => {
      expect(
        JSON.parse(
          window.localStorage.getItem(PREFERENCES_STORAGE_KEY) ?? "{}",
        ),
      ).toEqual({
        locale: "en-US",
        theme: "dark",
        motion: "standard",
      });
    });
    expect(document.documentElement).toHaveAttribute("lang", "en-US");
    expect(document.documentElement).toHaveAttribute(
      "data-motion",
      "standard",
    );
  });

  it("ignores corrupt or unsupported stored preference values", () => {
    window.localStorage.setItem(PREFERENCES_STORAGE_KEY, "{not-json");
    expect(readStoredPreferences()).toEqual({});

    window.localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        locale: "fr-FR",
        theme: "sepia",
        motion: "infinite",
      }),
    );
    expect(readStoredPreferences()).toEqual({});
  });
});
