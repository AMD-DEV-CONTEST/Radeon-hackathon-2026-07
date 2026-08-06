import { NextResponse } from 'next/server';
import { getAuthenticatedClient, AuthError } from '@/lib/supabase-server';

const EDITABLE_FIELDS = [
  'client_name',
  'project_type',
  'budget',
  'currency',
  'deadline',
] as const;

type EditableField = (typeof EDITABLE_FIELDS)[number];

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

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  // Only allow whitelisted fields
  const updates: Record<string, unknown> = {};
  for (const key of Object.keys(body)) {
    if (EDITABLE_FIELDS.includes(key as EditableField)) {
      updates[key] = body[key];
    }
  }

  if (Object.keys(updates).length === 0) {
    return NextResponse.json({ error: 'No valid fields to update' }, { status: 400 });
  }

  // Type-validate specific fields
  if ('budget' in updates && updates.budget !== null) {
    const n = Number(updates.budget);
    if (Number.isNaN(n) || n < 0) {
      return NextResponse.json({ error: 'Budget must be a non-negative number' }, { status: 400 });
    }
    updates.budget = n;
  }

  if ('currency' in updates && typeof updates.currency === 'string') {
    const validCurrencies = ['CNY', 'USD', 'EUR', 'GBP', 'JPY', 'SGD'];
    if (!validCurrencies.includes(updates.currency)) {
      return NextResponse.json({ error: 'Invalid currency' }, { status: 400 });
    }
  }

  if ('deadline' in updates && typeof updates.deadline === 'string') {
    const d = new Date(updates.deadline);
    if (Number.isNaN(d.getTime())) {
      return NextResponse.json({ error: 'Invalid deadline date' }, { status: 400 });
    }
  }

  updates.updated_at = new Date().toISOString();

  const { data, error } = await supabase
    .from('projects')
    .update(updates)
    .eq('id', params.id)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // Log the edit in agent_actions for timeline visibility
  await supabase.from('agent_actions').insert({
    project_id: params.id,
    action_type: 'status_updated',
    payload: { ...updates, source: 'inline_edit' },
  });

  return NextResponse.json({ project: data });
}
