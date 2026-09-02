export const CANDIDATE_QUERY_KEYS = {
  all: ["candidate"] as const,
  detail: (id: string) => [...CANDIDATE_QUERY_KEYS.all, "detail", id] as const,
  resume: (id: string) => [...CANDIDATE_QUERY_KEYS.all, "resume", id] as const,
} as const;

export const CANDIDATE_MUTATION_KEYS = {
  update: ["candidate", "update"] as const,
  analyzeResume: ["resume", "analyze"] as const,
} as const;
