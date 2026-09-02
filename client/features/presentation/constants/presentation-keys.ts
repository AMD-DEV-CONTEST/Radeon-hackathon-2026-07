export const PRESENTATION_QUERY_KEYS = {
  all: ["presentation"] as const,
  detail: (candidateId: string) =>
    [...PRESENTATION_QUERY_KEYS.all, "detail", candidateId] as const,
  report: (id: string) =>
    [...PRESENTATION_QUERY_KEYS.all, "report", id] as const,
  candidate: (id: string) =>
    [...PRESENTATION_QUERY_KEYS.all, "candidate", id] as const,
} as const;
