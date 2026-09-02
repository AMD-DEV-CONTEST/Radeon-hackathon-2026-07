function getEnv(name: string, fallback?: string): string {
  const value = process.env[name] ?? fallback;

  if (value === undefined || value.length === 0) {
    throw new Error(`Missing required environment variable: ${name}`);
  }

  return value;
}

function deriveWsUrl(apiBaseUrl: string): string {
  try {
    const url = new URL(apiBaseUrl);
    const trimmedPath = url.pathname.replace(/\/api\/v\d+\/?$/i, "");
    url.pathname = trimmedPath.length > 0 ? trimmedPath : "/";
    url.search = "";
    url.hash = "";
    return url.origin;
  } catch {
    return "http://localhost:8000";
  }
}

/**
 * Prefer NEXT_PUBLIC_API_URL, fall back to NEXT_PUBLIC_API_BASE_URL for
 * backward compatibility with existing deployments.
 */
export const env = {
  apiBaseUrl: getEnv(
    "NEXT_PUBLIC_API_URL",
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1"
  ),
  wsUrl: getEnv(
    "NEXT_PUBLIC_WS_URL",
    deriveWsUrl(
      process.env.NEXT_PUBLIC_API_URL ??
        process.env.NEXT_PUBLIC_API_BASE_URL ??
        "http://localhost:8000/api/v1"
    )
  ),
} as const;
