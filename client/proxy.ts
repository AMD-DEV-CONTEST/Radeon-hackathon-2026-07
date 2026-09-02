import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Must stay aligned with `AUTH_STORAGE_KEY` in `features/auth/store/auth.store.ts`.
 * Proxy can only observe cookies / headers — not `localStorage` / `sessionStorage`.
 */
const AUTH_STORAGE_KEY = "agentvox-auth";
const PUBLIC_ROUTES = ["/", "/login", "/register", "/forgot-password"] as const;
const AUTH_ENTRY_ROUTES = ["/login", "/register", "/forgot-password"] as const;
const PROTECTED_ROUTE_PREFIXES = [
  "/dashboard",
  "/resume",
  "/candidates",
  "/interviews",
  "/report",
  "/settings",
  "/agents",
  "/presentation",
  "/admin",
] as const;

interface PersistedAuthState {
  state?: {
    accessToken?: string | null;
    refreshToken?: string | null;
    isAuthenticated?: boolean;
  };
}

function normalizePathname(pathname: string): string {
  if (pathname.length > 1 && pathname.endsWith("/")) {
    return pathname.slice(0, -1);
  }
  return pathname;
}

function isPublicRoute(pathname: string): boolean {
  return PUBLIC_ROUTES.some((route) => route === pathname);
}

function isAuthEntryRoute(pathname: string): boolean {
  return AUTH_ENTRY_ROUTES.some((route) => route === pathname);
}

function isProtectedRoute(pathname: string): boolean {
  return PROTECTED_ROUTE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
}

function readBearerToken(request: NextRequest): string | null {
  const header = request.headers.get("authorization");
  if (!header) return null;

  const [scheme, token] = header.split(" ");
  if (!scheme || !token || scheme.toLowerCase() !== "bearer") return null;

  const trimmed = token.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function readTokenFromAuthStorageCookie(rawValue: string): string | null {
  try {
    const decoded = decodeURIComponent(rawValue);
    const parsed = JSON.parse(decoded) as PersistedAuthState;
    const accessToken = parsed.state?.accessToken;

    if (typeof accessToken === "string" && accessToken.trim().length > 0) {
      return accessToken.trim();
    }

    return null;
  } catch {
    const trimmed = rawValue.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
}

/**
 * Reuses the existing auth session contract:
 * - Zustand persist payload under `agentvox-auth`
 * - Optional `access_token` / `accessToken` cookies
 * - `Authorization: Bearer <token>` header
 */
function getAccessToken(request: NextRequest): string | null {
  const bearer = readBearerToken(request);
  if (bearer) return bearer;

  const storageCookie = request.cookies.get(AUTH_STORAGE_KEY)?.value;
  if (storageCookie) {
    const fromStorage = readTokenFromAuthStorageCookie(storageCookie);
    if (fromStorage) {
      return fromStorage;
    }
  }

  const accessTokenCookie =
    request.cookies.get("access_token")?.value ??
    request.cookies.get("accessToken")?.value;

  if (accessTokenCookie && accessTokenCookie.trim().length > 0) {
    return accessTokenCookie.trim();
  }

  return null;
}

function isAuthenticated(request: NextRequest): boolean {
  return getAccessToken(request) !== null;
}

function redirectTo(request: NextRequest, pathname: string): NextResponse {
  const url = request.nextUrl.clone();
  url.pathname = pathname;
  url.search = "";
  return NextResponse.redirect(url);
}

export function proxy(request: NextRequest): NextResponse {
  const pathname = normalizePathname(request.nextUrl.pathname);
  const authenticated = isAuthenticated(request);

  if (authenticated && isAuthEntryRoute(pathname)) {
    return redirectTo(request, "/dashboard");
  }

  if (!authenticated && isProtectedRoute(pathname)) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.search = "";
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  if (isPublicRoute(pathname) || isProtectedRoute(pathname)) {
    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all pathnames except:
     * - api routes
     * - Next.js internals (_next/static, _next/image)
     * - common static assets / metadata files
     */
    "/((?!api|_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt|.*\\..*).*)",
  ],
};
