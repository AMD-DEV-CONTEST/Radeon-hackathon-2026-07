import { createServerClient } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';

// Routes that don't require authentication
const PUBLIC_ROUTES = ['/login', '/demo', '/pricing'];
const PUBLIC_API_ROUTES = ['/api/cron', '/api/avatar', '/api/stripe'];

function isPublicRoute(pathname: string): boolean {
  // Exact match for public pages
  if (PUBLIC_ROUTES.includes(pathname)) return true;
  // API routes that work without auth
  if (PUBLIC_API_ROUTES.some((r) => pathname.startsWith(r))) return true;
  // Static assets and Next.js internals
  if (pathname.startsWith('/_next/') || pathname.includes('.')) return true;
  return false;
}

export async function middleware(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request });

  // Skip auth entirely in demo mode — the app runs without login
  if (process.env.NEXT_PUBLIC_DEMO_MODE === 'true') {
    return supabaseResponse;
  }

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          try {
            for (const { name, value } of cookiesToSet) {
              request.cookies.set(name, value);
            }
          } catch {}
          supabaseResponse = NextResponse.next({ request });
          for (const { name, value } of cookiesToSet) {
            supabaseResponse.cookies.set(name, value);
          }
        },
      },
    },
  );

  // Verify the user's session on every request.
  // getSession() reads the JWT from the cookie locally (0ms network),
  // unlike getUser() which makes a round-trip to Supabase auth servers.
  // The middleware only needs to know IF a session exists for route
  // guarding — actual token refresh happens in Server Components.
  const { data: { session } } = await supabase.auth.getSession();
  const user = session?.user ?? null;

  const { pathname } = request.nextUrl;

  // Redirect unauthenticated users to login (except public routes)
  if (!user && !isPublicRoute(pathname)) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = '/login';
    redirectUrl.searchParams.set('redirect', pathname);
    return NextResponse.redirect(redirectUrl);
  }

  // Redirect authenticated users away from /login
  if (user && pathname === '/login') {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = '/dashboard';
    redirectUrl.searchParams.delete('redirect');
    return NextResponse.redirect(redirectUrl);
  }

  return supabaseResponse;
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
};
