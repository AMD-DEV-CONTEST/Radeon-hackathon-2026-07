export const RESUME_QUERY_KEYS = {
  all: ["resume"] as const,
  detail: (id: string) => [...RESUME_QUERY_KEYS.all, "detail", id] as const,
} as const;

export const RESUME_MUTATION_KEYS = {
  upload: ["resume", "upload"] as const,
  delete: ["resume", "delete"] as const,
} as const;
