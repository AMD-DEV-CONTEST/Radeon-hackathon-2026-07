export const ADMIN_QUERY_KEYS = {
  all: ["admin"] as const,
  dashboard: () => [...ADMIN_QUERY_KEYS.all, "dashboard"] as const,
  analytics: () => [...ADMIN_QUERY_KEYS.all, "analytics"] as const,
  users: () => [...ADMIN_QUERY_KEYS.all, "users"] as const,
  interviews: () => [...ADMIN_QUERY_KEYS.all, "interviews"] as const,
  system: () => [...ADMIN_QUERY_KEYS.all, "system"] as const,
} as const;
