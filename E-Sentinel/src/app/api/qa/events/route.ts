import { NextResponse } from "next/server";
import { authorizeRequest } from "@/lib/api-auth";
import { ingestEvidenceEvent } from "@/lib/governance/event-store";
import { loadGovernanceContext } from "@/lib/governance/roles";
import { ensureTraceparent } from "@/lib/monitoring/tracing";

export async function POST(request: Request) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;

  try {
    const parsed = await request.json();
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return NextResponse.json({ error: "event must be an object" }, { status: 400 });
    }
    const body = { ...(parsed as Record<string, unknown>) };
    if (auth.user) {
      const context = await loadGovernanceContext(auth.user.id);
      if (!context?.tenantId) {
        return NextResponse.json({ error: "Authenticated user has no tenant context" }, { status: 403 });
      }
      if (context?.tenantId && body.tenant_id !== context.tenantId) {
        return NextResponse.json({ error: "Event tenant does not match authenticated user" }, { status: 403 });
      }
      body.tenant_id = context.tenantId;
      body.actor = { id: auth.user.id, type: "user", name: context?.profileName || undefined };
    }
    ensureTraceparent(body, request);
    const result = await ingestEvidenceEvent(body);
    return NextResponse.json(result, { status: result.status === "duplicate" ? 200 : 202 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid_event";
    const status = message.includes("must be") || message.includes("contains") || message === "event must be an object"
      ? 400
      : 500;
    return NextResponse.json({ error: message }, { status });
  }
}
