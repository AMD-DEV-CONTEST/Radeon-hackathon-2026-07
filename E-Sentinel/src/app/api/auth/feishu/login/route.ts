// ============================================================================
// GET /api/auth/feishu/login — initiates Feishu OAuth 2.0 scan-login flow.
// Redirects user to Feishu authorization page. State stored in httpOnly cookie.
// ============================================================================

import { NextResponse } from "next/server";
import { cookies } from "next/headers";

export async function GET() {
  const appId = process.env.FEISHU_APP_ID || "";
  const appUrl = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3001";
  const dashboardUrl = `/dashboard?tab=platforms`;

  if (!appId) {
    const url = new URL(`${dashboardUrl}&login=error&reason=no_app_id`, appUrl);
    return NextResponse.redirect(url);
  }

  const redirectUri = `${appUrl}/api/auth/feishu/callback`;
  const state = crypto.randomUUID();

  // Store state in httpOnly cookie for CSRF validation (10 min TTL)
  const cookieStore = await cookies();
  cookieStore.set("feishu_oauth_state", state, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: 600,
    path: "/",
  });

  const authUrl = new URL("https://open.feishu.cn/open-apis/authen/v1/authorize");
  authUrl.searchParams.set("app_id", appId);
  authUrl.searchParams.set("redirect_uri", redirectUri);
  authUrl.searchParams.set("state", state);
  authUrl.searchParams.set("scope", "im:message,im:chat,contact:user.base:readonly");

  return NextResponse.redirect(authUrl.toString());
}
