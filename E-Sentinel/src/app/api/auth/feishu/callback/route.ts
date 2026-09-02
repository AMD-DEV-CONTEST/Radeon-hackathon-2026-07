// ============================================================================
// GET /api/auth/feishu/callback — handles OAuth redirect from Feishu.
// Validates state (CSRF), exchanges code for user tokens,
// and stores them in platform_credentials.
// ============================================================================

import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const error = searchParams.get("error");
  const errorDescription = searchParams.get("error_description");

  const appUrl = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3001";
  const dashboardBase = `${appUrl}/dashboard?tab=platforms`;

  // Handle Feishu-reported errors (user denied, etc.)
  if (error) {
    const reason = errorDescription || error;
    return NextResponse.redirect(
      new URL(`${dashboardBase}&login=error&reason=${encodeURIComponent(reason)}`, dashboardBase),
    );
  }

  // Validate state for CSRF protection
  const cookieStore = await cookies();
  const storedState = cookieStore.get("feishu_oauth_state")?.value;

  if (!state || !storedState || state !== storedState) {
    return NextResponse.redirect(
      new URL(`${dashboardBase}&login=error&reason=csrf_mismatch`, dashboardBase),
    );
  }
  cookieStore.delete("feishu_oauth_state");

  if (!code) {
    return NextResponse.redirect(
      new URL(`${dashboardBase}&login=error&reason=no_code`, dashboardBase),
    );
  }

  const appId = process.env.FEISHU_APP_ID || "";
  const appSecret = process.env.FEISHU_APP_SECRET || "";

  if (!appId || !appSecret) {
    return NextResponse.redirect(
      new URL(`${dashboardBase}&login=error&reason=missing_env_credentials`, dashboardBase),
    );
  }

  try {
    // Step 1: Obtain app_access_token (server-to-server)
    const tokenRes = await fetch(
      "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app_id: appId, app_secret: appSecret }),
      },
    );
    const tokenData = (await tokenRes.json()) as {
      app_access_token?: string;
      code?: number;
      msg?: string;
    };

    if (!tokenData.app_access_token) {
      const reason = tokenData.msg || "failed_to_get_app_access_token";
      return NextResponse.redirect(
        new URL(`${dashboardBase}&login=error&reason=${encodeURIComponent(reason)}`, dashboardBase),
      );
    }

    const appAccessToken = tokenData.app_access_token;

    // Step 2: Exchange authorization code for user tokens
    const redirectUri = `${appUrl}/api/auth/feishu/callback`;
    const exchangeRes = await fetch(
      "https://open.feishu.cn/open-apis/authen/v1/access_token",
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${appAccessToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          grant_type: "authorization_code",
          code,
        }),
      },
    );
    const exchangeData = (await exchangeRes.json()) as {
      code?: number;
      msg?: string;
      data?: {
        access_token?: string;
        refresh_token?: string;
        expires_in?: number;
        open_id?: string;
        name?: string;
      };
    };

    if (!exchangeRes.ok || exchangeData.code !== 0 || !exchangeData.data) {
      const reason = exchangeData.msg || `exchange_failed_http_${exchangeRes.status}`;
      return NextResponse.redirect(
        new URL(`${dashboardBase}&login=error&reason=${encodeURIComponent(reason)}`, dashboardBase),
      );
    }

    const { access_token, refresh_token, expires_in, open_id } = exchangeData.data;

    if (!supabaseAdmin) {
      return NextResponse.redirect(
        new URL(`${dashboardBase}&login=error&reason=supabase_not_configured`, dashboardBase),
      );
    }

    // Step 3: Look up the feishu platform id
    const { data: platforms, error: platformError } = await supabaseAdmin
      .from("platforms")
      .select("id")
      .eq("code", "feishu")
      .single();

    if (platformError || !platforms) {
      console.error("[Feishu OAuth] Platform lookup failed:", platformError);
      return NextResponse.redirect(
        new URL(`${dashboardBase}&login=error&reason=platform_not_found`, dashboardBase),
      );
    }

    const platformId = platforms.id;
    const expiresAt = expires_in
      ? new Date(Date.now() + expires_in * 1000).toISOString()
      : null;

    // Step 4: Upsert credentials into platform_credentials
    const credentialRows: Array<{
      credential_key: string;
      credential_value: string;
    }> = [
      { credential_key: "user_access_token", credential_value: access_token || "" },
      { credential_key: "refresh_token", credential_value: refresh_token || "" },
      { credential_key: "user_open_id", credential_value: open_id || "" },
    ];

    for (const cred of credentialRows) {
      if (!cred.credential_value) continue;
      const { error: upsertError } = await supabaseAdmin
        .from("platform_credentials")
        .upsert(
          {
            platform_id: platformId,
            credential_key: cred.credential_key,
            credential_value: cred.credential_value,
            expires_at:
              cred.credential_key === "user_access_token" ? expiresAt : null,
            metadata:
              cred.credential_key === "user_access_token"
                ? { open_id, scopes: "im:message,im:chat,contact:user.base:readonly" }
                : {},
            updated_at: new Date().toISOString(),
          },
          { onConflict: "platform_id,credential_key" },
        );
      if (upsertError) {
        console.error(
          `[Feishu OAuth] Failed to upsert ${cred.credential_key}:`,
          upsertError,
        );
      }
    }

    return NextResponse.redirect(
      new URL(`${dashboardBase}&login=success`, dashboardBase),
    );
  } catch (err) {
    console.error("[Feishu OAuth] Unexpected error:", err);
    const reason = err instanceof Error ? err.message : "internal_error";
    return NextResponse.redirect(
      new URL(`${dashboardBase}&login=error&reason=${encodeURIComponent(reason)}`, dashboardBase),
    );
  }
}
