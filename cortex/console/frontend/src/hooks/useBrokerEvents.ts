import { useEffect, useReducer } from "react";
import { consoleReducer, ConsoleState } from "../state/store";

export function useBrokerEvents(url: string) {
  const [state, dispatch] = useReducer(consoleReducer, { articles: [], connected: false } as ConsoleState);
  useEffect(() => {
    const ws = new WebSocket(url);
    ws.onopen = () => dispatch({ type: "connected" });
    ws.onclose = () => dispatch({ type: "disconnected" });
    ws.onmessage = (ev: MessageEvent) => {
      try {
        const env = JSON.parse(ev.data);
        if (env.type === "event") dispatch({ type: "event", env: env.payload });
      } catch { /* ignore */ }
    };
    return () => ws.close();
  }, [url]);
  return state;
}
