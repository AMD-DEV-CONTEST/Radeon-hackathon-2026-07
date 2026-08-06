import { useEffect, useReducer } from "react";
import { consoleReducer, ConsoleState } from "../state/store";

export function useBrokerEvents(url: string) {
  const [state, dispatch] = useReducer(consoleReducer, { articles: [], activities: [], connected: false } as ConsoleState);
  useEffect(() => {
    fetch("/api/attack-matrix")
      .then(r => r.json())
      .then(data => {
        if (data?.counts) {
          for (const [attackId, count] of Object.entries(data.counts)) {
            for (let i = 0; i < (count as number); i++) {
              dispatch({ type: "event", env: { event: "article.published", data: { article: { id: `init-${attackId}-${i}`, type: "finding", content: `Historical finding for ${attackId}`, payload: { attack_id: attackId } } } } });
            }
          }
        }
      })
      .catch(() => {});

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
