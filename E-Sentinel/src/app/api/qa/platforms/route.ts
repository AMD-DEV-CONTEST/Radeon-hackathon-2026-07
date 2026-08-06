import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { authorizeRequest } from "@/lib/api-auth";

export async function GET(request: Request) {
  const auth = await authorizeRequest(request);
  if (auth.error) return auth.error;
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { data, error } = await supabaseAdmin
      .from("platforms")
      .select("*")
      .order("name");

    if (error) throw error;

    return NextResponse.json({ platforms: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : (typeof error === "string" ? error : "internal_error");
    console.error("[Platforms] GET error:", message, "| typeof:", typeof error);
    return NextResponse.json({ error: message || "internal_error" }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { name, code, bot_type, api_endpoint } = body;

    if (!name || !code) {
      return NextResponse.json({ error: "name and code are required" }, { status: 400 });
    }

    const validBotTypes = ["third_party", "native", "hybrid"];
    const botType = validBotTypes.includes(bot_type) ? bot_type : "third_party";

    const { data, error } = await supabaseAdmin
      .from("platforms")
      .insert({ name, code, bot_type: botType, api_endpoint: api_endpoint || null })
      .select()
      .single();

    if (error) {
      if (error.code === "23505") {
        return NextResponse.json({ error: "Platform code already exists" }, { status: 409 });
      }
      throw error;
    }

    return NextResponse.json({ platform: data }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : (typeof error === "string" ? error : "internal_error");
    console.error("[Platforms] POST error:", message, "| typeof:", typeof error);
    return NextResponse.json({ error: message || "internal_error" }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { id, name, code, bot_type, api_endpoint, config } = body;

    if (!id) {
      return NextResponse.json({ error: "id is required" }, { status: 400 });
    }

    const updates: Record<string, unknown> = {};
    if (name !== undefined) updates.name = name;
    if (code !== undefined) updates.code = code;
    if (bot_type !== undefined) updates.bot_type = bot_type;
    if (api_endpoint !== undefined) updates.api_endpoint = api_endpoint;
    if (config !== undefined) updates.config = config;

    if (Object.keys(updates).length === 0) {
      return NextResponse.json({ error: "No fields to update" }, { status: 400 });
    }

    const { data, error } = await supabaseAdmin
      .from("platforms")
      .update(updates)
      .eq("id", id)
      .select()
      .single();

    if (error) throw error;

    return NextResponse.json({ platform: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : (typeof error === "string" ? error : "internal_error");
    console.error("[Platforms] PATCH error:", message, "| typeof:", typeof error);
    return NextResponse.json({ error: message || "internal_error" }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const url = new URL(request.url);
    const id = url.searchParams.get("id");

    if (!id) {
      return NextResponse.json({ error: "id query param is required" }, { status: 400 });
    }

    const { error } = await supabaseAdmin
      .from("platforms")
      .delete()
      .eq("id", id);

    if (error) throw error;

    return NextResponse.json({ status: "deleted", id });
  } catch (error) {
    const message = error instanceof Error ? error.message : (typeof error === "string" ? error : "internal_error");
    console.error("[Platforms] DELETE error:", message, "| typeof:", typeof error);
    return NextResponse.json({ error: message || "internal_error" }, { status: 500 });
  }
}
