import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedClient, AuthError } from '@/lib/supabase-server';

export const dynamic = 'force-dynamic';

export async function GET(
  _req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const supabase = await getAuthenticatedClient();

    const { data: project } = await supabase
      .from('projects')
      .select('id, client_name, project_type')
      .eq('id', params.id)
      .single();

    if (!project) return NextResponse.json({ error: 'Project not found' }, { status: 404 });

    const { data: action } = await supabase
      .from('agent_actions')
      .select('payload, created_at')
      .eq('project_id', params.id)
      .eq('action_type', 'contract_generated')
      .order('created_at', { ascending: false })
      .limit(1)
      .maybeSingle();

    if (!action?.payload) {
      return NextResponse.json({ error: 'No contract found for this project' }, { status: 404 });
    }

    const contract = (action.payload as { contract?: string }).contract ?? '';
    const filename = `contract-${project.client_name.replace(/\s+/g, '-')}.md`;

    return new Response(contract, {
      headers: {
        'Content-Type': 'text/markdown; charset=utf-8',
        'Content-Disposition': `attachment; filename="${filename}"`,
      },
    });
  } catch (e) {
    if (e instanceof AuthError) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
