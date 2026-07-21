export interface Article {
  id: string;
  type: "finding" | "insight" | "warning" | "precedent" | "procedure";
  content: string;
  payload?: Record<string, unknown>;
  trust_score?: number | null;
  scope?: string;
  cites?: string[];
  agent_signature?: string;
  org_signature?: string | null;
}

export interface BrokerEvent {
  event: string;
  data: { article?: Article; [k: string]: unknown };
}

export interface ConsoleState {
  articles: Article[];
  connected: boolean;
}

export type Action =
  | { type: "connected" }
  | { type: "disconnected" }
  | { type: "event"; env: BrokerEvent };

export function consoleReducer(state: ConsoleState, action: Action): ConsoleState {
  switch (action.type) {
    case "connected": return { ...state, connected: true };
    case "disconnected": return { ...state, connected: false };
    case "event":
      if (action.env.event === "article.published" && action.env.data.article) {
        const a = action.env.data.article;
        if (state.articles.find(x => x.id === a.id)) return state;
        return { ...state, articles: [a, ...state.articles].slice(0, 1000) };
      }
      return state;
  }
}
