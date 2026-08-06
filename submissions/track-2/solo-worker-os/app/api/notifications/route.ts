import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedClient, AuthError } from '@/lib/supabase-server';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const supabase = await getAuthenticatedClient();
    const { data } = await supabase
      .from('notifications')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(20);

    return NextResponse.json({ notifications: data ?? [] });
  } catch (e) {
    if (e instanceof AuthError) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

export async function PATCH(req: NextRequest) {
  try {
    const supabase = await getAuthenticatedClient();
    const body = await req.json() as { id?: string; all?: boolean };

    if (body.all) {
      await supabase.from('notifications').update({ read: true }).eq('read', false);
    } else if (body.id) {
      await supabase.from('notifications').update({ read: true }).eq('id', body.id);
    }

    return NextResponse.json({ ok: true });
  } catch (e) {
    if (e instanceof AuthError) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
