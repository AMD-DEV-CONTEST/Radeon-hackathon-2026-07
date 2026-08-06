import { NextResponse } from 'next/server';
import { getAuthenticatedClient, AuthError } from '@/lib/supabase-server';
import { getMemoryStore, type StoreContext } from '@/lib/memory/store';

export const dynamic = 'force-dynamic';

/**
 * GET /api/conversations
 * Returns a list of all conversations for the authenticated user,
 * sorted by most recent activity. Each entry includes a preview of
 * the first user message.
 */
export async function GET() {
  let supabase;
  let user: { id: string } | null = null;
  try {
    supabase = await getAuthenticatedClient();
    const { data: { user: u } } = await supabase.auth.getUser().catch(() => ({ data: { user: null } }));
    user = u;
  } catch (e) {
    if (e instanceof AuthError) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }

  const storeCtx: StoreContext = {
    ...(user && { userId: user.id }),
    supabase,
  };

  const store = getMemoryStore();
  const conversations = await store.listConversations(storeCtx);

  return NextResponse.json({ conversations });
}
