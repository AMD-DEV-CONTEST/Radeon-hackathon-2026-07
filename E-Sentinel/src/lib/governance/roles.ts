import { supabaseAdmin } from "@/lib/supabase";

export type GovernanceRole = "admin" | "operator" | "agent" | "viewer";
export type LegacyRole = GovernanceRole | "team_lead" | string;
export type DataScope = "all" | "team" | "self";

export interface GovernanceContext {
  userId: string;
  role: GovernanceRole;
  dataScope: DataScope;
  tenantId: string | null;
  teamId: string | null;
  profileName: string | null;
}

export function normalizeRole(role: LegacyRole | null | undefined): GovernanceRole {
  if (role === "admin" || role === "operator" || role === "agent" || role === "viewer") {
    return role;
  }
  if (role === "team_lead") return "operator";
  return "viewer";
}

export function dataScopeForRole(role: GovernanceRole): DataScope {
  if (role === "admin") return "all";
  if (role === "operator" || role === "viewer") return "team";
  return "self";
}

export function canWrite(role: GovernanceRole): boolean {
  return role === "admin" || role === "operator";
}

export function isWithinDataScope(
  context: Pick<GovernanceContext, "dataScope" | "userId" | "teamId" | "tenantId">,
  resource: { ownerId?: string | null; teamId?: string | null; tenantId?: string | null },
): boolean {
  if (context.tenantId && resource.tenantId && context.tenantId !== resource.tenantId) return false;
  if (context.dataScope === "all") return true;
  if (context.dataScope === "self") return resource.ownerId === context.userId;
  return Boolean(context.teamId && resource.teamId && context.teamId === resource.teamId);
}

export async function loadGovernanceContext(userId: string): Promise<GovernanceContext | null> {
  if (!supabaseAdmin) return null;

  const [{ data: profile }, { data: assignment }] = await Promise.all([
    supabaseAdmin
      .from("profiles")
      .select("id, name, role, team_id, tenant_id")
      .eq("id", userId)
      .maybeSingle(),
    supabaseAdmin
      .from("user_roles")
      .select("role")
      .eq("profile_id", userId)
      .maybeSingle(),
  ]);

  if (!profile && !assignment) return null;

  const role = normalizeRole(assignment?.role || profile?.role);
  return {
    userId,
    role,
    dataScope: dataScopeForRole(role),
    tenantId: typeof profile?.tenant_id === "string" ? profile.tenant_id : null,
    teamId: typeof profile?.team_id === "string" ? profile.team_id : null,
    profileName: typeof profile?.name === "string" ? profile.name : null,
  };
}
