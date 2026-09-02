import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

const queryState = new Map<string, boolean>();
const queryListeners = new Map<
  string,
  Set<(event: MediaQueryListEvent) => void>
>();

export function setMediaQuery(query: string, matches: boolean) {
  queryState.set(query, matches);
  const event = { matches, media: query } as MediaQueryListEvent;
  queryListeners.get(query)?.forEach((listener) => listener(event));
}

function createMediaQueryList(query: string): MediaQueryList {
  const listeners =
    queryListeners.get(query) ??
    new Set<(event: MediaQueryListEvent) => void>();
  queryListeners.set(query, listeners);

  return {
    get matches() {
      return queryState.get(query) ?? false;
    },
    media: query,
    onchange: null,
    addEventListener: (
      _type: string,
      listener: EventListenerOrEventListenerObject,
    ) => {
      if (typeof listener === "function") {
        listeners.add(listener as (event: MediaQueryListEvent) => void);
      }
    },
    removeEventListener: (
      _type: string,
      listener: EventListenerOrEventListenerObject,
    ) => {
      if (typeof listener === "function") {
        listeners.delete(listener as (event: MediaQueryListEvent) => void);
      }
    },
    addListener: (listener) => {
      if (listener) {
        listeners.add(listener);
      }
    },
    removeListener: (listener) => {
      if (listener) {
        listeners.delete(listener);
      }
    },
    dispatchEvent: () => true,
  };
}

Object.defineProperty(window, "matchMedia", {
  configurable: true,
  value: vi.fn(createMediaQueryList),
});

beforeEach(() => {
  window.localStorage.clear();
  queryState.clear();
  queryListeners.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-theme-preference");
  document.documentElement.removeAttribute("data-motion");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
