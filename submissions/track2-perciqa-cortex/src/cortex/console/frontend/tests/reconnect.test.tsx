import { describe, it, expect, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { App } from "../src/App";

class FakeWS {
  static instances: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  constructor(public url: string) { FakeWS.instances.push(this); }
  close() { this.onclose?.(); }
}
vi.stubGlobal("WebSocket", FakeWS);

describe("Reconnect banner", () => {
  it("shows a reconnecting banner when the WS closes", () => {
    render(<App />);
    const ws = FakeWS.instances[FakeWS.instances.length - 1];
    act(() => ws.onopen?.());
    act(() => ws.onclose?.());
    expect(screen.getByText(/reconnecting/i)).toBeTruthy();
  });
});
