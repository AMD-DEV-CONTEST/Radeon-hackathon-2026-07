// ============================================================================
// GET/POST /api/admin/store-switches — store-level circuit breaker config
// Controls which Tmall stores get AI real replies (white-list per store).
// ============================================================================

import { NextResponse } from "next/server";
import { getConfigString, setConfigString } from "@/lib/system-config";
import { authorizeRequest } from "@/lib/api-auth";

const STORES_CONFIG_KEY = "tmall_real_reply_stores";

export async function GET(request: Request) {
  const auth = await authorizeRequest(request);
  if (auth.error) return auth.error;
  try {
    const raw = await getConfigString(STORES_CONFIG_KEY, "{}");
    let stores: Record<string, boolean>;
    try {
      stores = JSON.parse(raw);
    } catch {
      stores = {};
    }
    return NextResponse.json({ stores });
  } catch (err) {
    const message = err instanceof Error ? err.message : "internal_error";
    console.error("[StoreSwitches] GET error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;
  try {
    const body = await request.json().catch(() => ({}));
    const { store_nick, enabled } = body;

    if (!store_nick || typeof store_nick !== "string") {
      return NextResponse.json({ error: "store_nick (string) is required" }, { status: 400 });
    }

    if (typeof enabled !== "boolean") {
      return NextResponse.json({ error: "enabled (boolean) is required" }, { status: 400 });
    }

    // Read current stores
    const raw = await getConfigString(STORES_CONFIG_KEY, "{}");
    let stores: Record<string, boolean>;
    try {
      stores = JSON.parse(raw);
    } catch {
      stores = {};
    }

    stores[store_nick] = enabled;

    const ok = await setConfigString(STORES_CONFIG_KEY, JSON.stringify(stores));
    if (!ok) {
      return NextResponse.json({ error: "Failed to save store config" }, { status: 500 });
    }

    return NextResponse.json({ stores, updated: store_nick, enabled });
  } catch (err) {
    const message = err instanceof Error ? err.message : "internal_error";
    console.error("[StoreSwitches] POST error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
