// POST /api/auth/signup — auto-create profile + user_role after Supabase signup
import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function POST(request: Request) {
  try {
    const { userId, name } = await request.json();
    if (!userId) return NextResponse.json({ error: "userId required" }, { status: 400 });

    if (!supabaseAdmin) {
      return NextResponse.json({ error: "supabaseAdmin not configured" }, { status: 500 });
    }

    // Create profile
    const { error: profileError } = await supabaseAdmin
      .from("profiles")
      .upsert({ id: userId, name: name || "新用户", role: "operator", tenant_id: "default" }, { onConflict: "id" });

    if (profileError) {
      console.error("[signup] profile creation failed:", profileError.message);
      return NextResponse.json({ error: profileError.message }, { status: 500 });
    }

    // Create user_role
    const { error: roleError } = await supabaseAdmin
      .from("user_roles")
      .upsert({ profile_id: userId, role: "operator", tenant_id: "default" }, { onConflict: "profile_id,tenant_id" });

    if (roleError) {
      console.error("[signup] role creation failed:", roleError.message);
      return NextResponse.json({ error: roleError.message }, { status: 500 });
    }

    return NextResponse.json({ success: true, role: "operator" });
  } catch (error) {
    console.error("[signup] unexpected error:", error instanceof Error ? error.message : "unknown");
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
