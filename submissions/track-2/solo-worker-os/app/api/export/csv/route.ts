import { NextResponse } from 'next/server';
import { getAuthenticatedClient, AuthError } from '@/lib/supabase-server';
import type { Project } from '@/lib/types';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const supabase = await getAuthenticatedClient();
    const { data, error } = await supabase
      .from('projects')
      .select('id, client_name, project_type, status, budget, currency, deadline, created_at')
      .order('created_at', { ascending: false });

    if (error) return NextResponse.json({ error: error.message }, { status: 500 });

    const projects = (data as Project[]) ?? [];

    const headers = ['id', 'client_name', 'project_type', 'status', 'budget', 'currency', 'deadline', 'created_at'];
    const rows = projects.map((p) => [
      p.id,
      `"${(p.client_name ?? '').replace(/"/g, '""')}"`,
      `"${(p.project_type ?? '').replace(/"/g, '""')}"`,
      p.status,
      p.budget,
      p.currency,
      p.deadline,
      p.created_at ?? '',
    ].join(','));

    const csv = [headers.join(','), ...rows].join('\n');

    return new Response(csv, {
      headers: {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': `attachment; filename="projects-${new Date().toISOString().slice(0,10)}.csv"`,
      },
    });
  } catch (e) {
    if (e instanceof AuthError) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
