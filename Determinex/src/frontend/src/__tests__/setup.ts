import "@testing-library/jest-dom";
import { vi } from "vitest";

// Mock the Tauri API since tests run in jsdom, not Tauri
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn().mockResolvedValue({}),
}));
