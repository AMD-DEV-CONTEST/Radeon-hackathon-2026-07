import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedClient, AuthError } from '@/lib/supabase-server';

export const dynamic = 'force-dynamic';

function authResponse(e: unknown) {
  if (e instanceof AuthError) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
}

export async function GET() {
  try {
    const supabase = await getAuthenticatedClient();
    const { data } = await supabase
      .from('knowledge_docs')
      .select('id, title, content, doc_type, tags, created_at')
      .order('created_at', { ascending: false });

    return NextResponse.json({ docs: data ?? [] });
  } catch (e) {
    return authResponse(e);
  }
}

export async function POST(req: NextRequest) {
  try {
    const supabase = await getAuthenticatedClient();
    const body = await req.json() as { title?: string; content?: string; doc_type?: string; tags?: string[] };
    const { title, content, doc_type = 'note', tags = [] } = body;
    if (!title?.trim() || !content?.trim()) {
      return NextResponse.json({ error: 'title and content are required' }, { status: 400 });
    }

    const { data, error } = await supabase
      .from('knowledge_docs')
      .insert({ title: title.trim(), content: content.trim(), doc_type, tags })
      .select()
      .single();

    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
    return NextResponse.json({ doc: data }, { status: 201 });
  } catch (e) {
    return authResponse(e);
  }
}

export async function PUT(req: NextRequest) {
  try {
    const supabase = await getAuthenticatedClient();
    const body = await req.json() as { id: string; title?: string; content?: string; doc_type?: string; tags?: string[] };
    const { id, title, content, doc_type, tags } = body;
    if (!id) return NextResponse.json({ error: 'id required' }, { status: 400 });

    const updates: Record<string, unknown> = {};
    if (title?.trim()) updates.title = title.trim();
    if (content?.trim()) updates.content = content.trim();
    if (doc_type) updates.doc_type = doc_type;
    if (tags !== undefined) updates.tags = tags;

    const { data, error } = await supabase
      .from('knowledge_docs')
      .update(updates)
      .eq('id', id)
      .select()
      .single();

    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
    return NextResponse.json({ doc: data });
  } catch (e) {
    return authResponse(e);
  }
}

export async function DELETE(req: NextRequest) {
  try {
    const supabase = await getAuthenticatedClient();
    const { searchParams } = new URL(req.url);
    const id = searchParams.get('id');
    if (!id) return NextResponse.json({ error: 'id required' }, { status: 400 });

    const { error } = await supabase.from('knowledge_docs').delete().eq('id', id);
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });

    return NextResponse.json({ ok: true });
  } catch (e) {
    return authResponse(e);
  }
}
