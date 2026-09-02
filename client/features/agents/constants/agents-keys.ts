export const AGENTS_QUERY_KEYS = {
  all: ["agents"] as const,
  overview: () => [...AGENTS_QUERY_KEYS.all, "overview"] as const,
  status: () => [...AGENTS_QUERY_KEYS.all, "status"] as const,
  logs: () => [...AGENTS_QUERY_KEYS.all, "logs"] as const,
  metrics: () => [...AGENTS_QUERY_KEYS.all, "metrics"] as const,
} as const;
