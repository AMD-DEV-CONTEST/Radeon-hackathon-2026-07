import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedClient, AuthError } from '@/lib/supabase-server';
import { STAGE_ORDER } from '@/lib/workflow';
import type { ChecksMap } from '@/lib/workflow';

export const dynamic = 'force-dynamic';

// GET /api/workflow/[id]
export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  try {
    const supabase = await getAuthenticatedClient();
    const { data } = await supabase
      .from('workflow_steps')
      .select('*')
      .eq('project_id', params.id)
      .maybeSingle();

    if (!data) {
      return NextResponse.json({ stage: 'kickoff', checks: {} });
    }
    return NextResponse.json({ stage: data.stage, checks: data.checks });
  } catch (e) {
    if (e instanceof AuthError) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

// PATCH /api/workflow/[id]
export async function PATCH(req: NextRequest, { params }: { params: { id: string } }) {
  try {
    const supabase = await getAuthenticatedClient();
    const body = await req.json() as { checkKey?: string; checked?: boolean; advanceStage?: boolean };

    const { data: existing } = await supabase
      .from('workflow_steps')
      .select('*')
      .eq('project_id', params.id)
      .maybeSingle();

    let stage: string = existing?.stage ?? 'kickoff';
    let checks: ChecksMap = (existing?.checks as ChecksMap) ?? {};

    if (body.checkKey !== undefined && body.checked !== undefined) {
      checks = { ...checks, [body.checkKey]: body.checked };
    }

    if (body.advanceStage) {
      const idx = STAGE_ORDER.indexOf(stage);
      if (idx < STAGE_ORDER.length - 1) {
        stage = STAGE_ORDER[idx + 1];
      }
    }

    await supabase
      .from('workflow_steps')
      .upsert({ project_id: params.id, stage, checks }, { onConflict: 'project_id' });

    return NextResponse.json({ stage, checks });
  } catch (e) {
    if (e instanceof AuthError) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
