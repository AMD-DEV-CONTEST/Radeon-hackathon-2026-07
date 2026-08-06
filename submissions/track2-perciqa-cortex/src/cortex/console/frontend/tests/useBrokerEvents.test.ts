import { describe, it, expect, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useBrokerEvents } from "../src/hooks/useBrokerEvents";

class FakeWS {
  static instances: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) { FakeWS.instances.push(this); }
  close() { this.onclose?.(); }
  fire(data: string) { this.onmessage?.({ data }); }
}

vi.stubGlobal("WebSocket", FakeWS);

describe("useBrokerEvents", () => {
  it("feeds article.published events to the article reducer", () => {
    const { result } = renderHook(() => useBrokerEvents("ws://localhost:8080/ws/events"));
    const fake = FakeWS.instances[FakeWS.instances.length - 1];
    act(() => { fake.onopen?.(); });
    act(() => {
      fake.fire(JSON.stringify({ type: "event", payload: { event: "article.published", data: { article: { id: "a1", type: "finding", content: "x" } } } }));
    });
    expect(result.current.articles.length).toBe(1);
    expect(result.current.articles[0].id).toBe("a1");
  });
});
