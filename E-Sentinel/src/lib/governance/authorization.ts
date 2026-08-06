import { NextResponse } from "next/server";
import { authorizeRequest, type AuthorizedRequest } from "@/lib/api-auth";
import { loadGovernanceContext, type GovernanceContext } from "@/lib/governance/roles";

export interface GovernanceAuthorization {
  auth: AuthorizedRequest;
  context: GovernanceContext | null;
  error: NextResponse | null;
}

/**
 * Route-level governance authorization for service-role backed APIs.
 *
 * Bearer requests resolve tenant scope from the server-side profile. Internal
 * API-key requests must provide an explicit x-tenant-id because service keys
 * do not carry a user governance context. Missing tenant scope is rejected.
 */
export async function authorizeGovernanceRequest(
  request: Request,
  options: { mutation?: boolean } = {},
): Promise<GovernanceAuthorization> {
  const auth = await authorizeRequest(request, options);
  if (auth.error) {
    return { auth, context: null, error: auth.error };
  }

  if (auth.authType === "bearer") {
    if (!auth.user) {
      return failClosed(auth, "Governance context required");
    }
    const context = await loadGovernanceContext(auth.user.id);
    if (!context?.tenantId) {
      return failClosed(auth, "Governance context required");
    }
    return { auth, context, error: null };
  }

  const tenantId = request.headers.get("x-tenant-id")?.trim();
  if (!tenantId) {
    return failClosed(auth, "Tenant scope required");
  }

  return {
    auth,
    context: {
      userId: "service",
      role: "operator",
      dataScope: "all",
      tenantId,
      teamId: null,
      profileName: null,
    },
    error: null,
  };
}

function failClosed(
  auth: AuthorizedRequest & { error: NextResponse | null },
  message: string,
): GovernanceAuthorization {
  return {
    auth,
    context: null,
    error: NextResponse.json({ error: message }, { status: 403 }),
  };
}
