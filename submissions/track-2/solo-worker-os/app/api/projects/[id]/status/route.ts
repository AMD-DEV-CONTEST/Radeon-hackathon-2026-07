import { NextResponse } from 'next/server';
import { getAuthenticatedClient, AuthError } from '@/lib/supabase-server';
import type { ProjectStatus } from '@/lib/types';

const VALID_STATUSES: ProjectStatus[] = ['active', 'delivered', 'invoiced', 'paid'];

export async function PATCH(
  req: Request,
  { params }: { params: { id: string } }
) {
  let supabase;
  try {
    supabase = await getAuthenticatedClient();
  } catch (e) {
    if (e instanceof AuthError) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }

  let body: { status?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const status = body.status as string;
  if (!VALID_STATUSES.includes(status as ProjectStatus)) {
    return NextResponse.json({ error: 'Invalid status' }, { status: 400 });
  }

  const { data, error } = await supabase
    .from('projects')
    .update({ status })
    .eq('id', params.id)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  await supabase.from('agent_actions').insert({
    project_id: params.id,
    action_type: 'status_updated',
    payload: { status, source: 'direct_ui' },
  });

  return NextResponse.json({ project: data });
}
