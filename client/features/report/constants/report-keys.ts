export const REPORT_QUERY_KEYS = {
  all: ["report"] as const,
  detail: (id: string) => [...REPORT_QUERY_KEYS.all, "detail", id] as const,
  interview: (id: string) =>
    [...REPORT_QUERY_KEYS.all, "interview", id] as const,
} as const;

export const REPORT_MUTATION_KEYS = {
  generate: ["report", "generate"] as const,
} as const;
