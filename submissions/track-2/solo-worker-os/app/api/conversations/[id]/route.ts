import { NextResponse } from 'next/server';
import { getAuthenticatedClient, AuthError } from '@/lib/supabase-server';
import { getMemoryStore, type StoreContext } from '@/lib/memory/store';

export const dynamic = 'force-dynamic';

/**
 * GET /api/conversations/[id]
 * Returns the full message history for a specific conversation.
 *
 * Query params:
 *   ?limit=N — max messages to return (default 50, max 200)
 */
export async function GET(
  _req: Request,
  { params }: { params: { id: string } },
) {
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

  const url = new URL(_req.url);
  const limitParam = url.searchParams.get('limit');
  const limit = Math.min(Math.max(parseInt(limitParam ?? '50', 10) || 50, 1), 200);

  const storeCtx: StoreContext = {
    ...(user && { userId: user.id }),
    supabase,
  };

  const store = getMemoryStore();
  const messages = await store.loadHistory(params.id, storeCtx, limit);

  return NextResponse.json({ messages, conversationId: params.id });
}
