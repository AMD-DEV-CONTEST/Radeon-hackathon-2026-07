import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { getPermissions, type Role } from "@/lib/rbac";
import { authorizeRequest } from "@/lib/api-auth";

export async function GET(request: Request) {
  try {
    const auth = await authorizeRequest(request);
    if (auth.error) return auth.error;
    if (!auth.user) {
      return NextResponse.json({ role: auth.role || "operator", permissions: getPermissions(auth.role || "operator") });
    }
    const profileId = auth.user.id;

    if (!profileId || !supabaseAdmin) return NextResponse.json({ role: "viewer" as Role, permissions: getPermissions("viewer") });

    // Look up role
    const { data: roleData } = await supabaseAdmin
      .from("user_roles")
      // user_roles has both assigned_by and profile_id foreign keys to profiles.
      // Disambiguate the relationship so Supabase/PostgREST returns the user's profile.
      .select("role, profiles!user_roles_profile_id_fkey(name, role)")
      .eq("profile_id", profileId)
      .maybeSingle();

    if (!roleData) {
      return NextResponse.json({
        role: "viewer" as Role,
        permissions: getPermissions("viewer"),
      });
    }

    const role = roleData.role as Role;
    return NextResponse.json({
      role,
      permissions: getPermissions(role),
      profile: roleData.profiles,
    });
  } catch (error) {
    console.error("[Auth] profile lookup failed:", error instanceof Error ? error.message : "unknown error");
    return NextResponse.json({ error: "Unable to resolve user permissions" }, { status: 500 });
  }
}
