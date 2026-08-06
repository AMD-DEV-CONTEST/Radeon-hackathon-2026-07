import { NextResponse } from 'next/server';
import { getAuthenticatedClient, AuthError } from '@/lib/supabase-server';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const supabase = await getAuthenticatedClient();

    const { data } = await supabase
      .from('projects')
      .select('id, client_name, project_type, status')
      .order('created_at', { ascending: false })
      .limit(20);

    return NextResponse.json({ projects: data ?? [] });
  } catch (e) {
    if (e instanceof AuthError) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
