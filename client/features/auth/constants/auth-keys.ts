export const AUTH_QUERY_KEYS = {
  currentUser: ["auth", "me"] as const,
} as const;

export const AUTH_MUTATION_KEYS = {
  login: ["auth", "login"] as const,
  register: ["auth", "register"] as const,
  forgotPassword: ["auth", "forgot-password"] as const,
  logout: ["auth", "logout"] as const,
} as const;
