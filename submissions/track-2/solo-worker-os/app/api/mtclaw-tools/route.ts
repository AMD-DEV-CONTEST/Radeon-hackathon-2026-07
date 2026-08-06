import { NextRequest, NextResponse } from 'next/server';
import { createServiceClient } from '@/lib/supabase-server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * MTClaw Fast-Path Tool API
 *
 * These endpoints are called by MTClaw's Function Router shell scripts
 * to bypass the LLM for simple data queries ("垂类加速").
 *
 * MTClaw's routing model matches user intent to these tools; when matched,
 * the shell script calls this API directly — no LLM round-trip needed.
 */

export async function GET(req: NextRequest) {
  const searchParams = req.nextUrl.searchParams;
  const action = searchParams.get('action') ?? 'overview';

  const supabase = createServiceClient();

  try {
    switch (action) {
      case 'overview': {
        const { data: projects } = await supabase
          .from('projects')
          .select('*');

        const all = projects ?? [];
        const active = all.filter((p: { status: string }) => p.status === 'active');
        const overdue = all.filter((p: { status: string }) => p.status === 'overdue');
        const completed = all.filter((p: { status: string }) => p.status === 'completed' || p.status === 'delivered');
        const totalRevenue = all.reduce((sum: number, p: { budget: number }) => sum + (p.budget ?? 0), 0);

        return NextResponse.json({
          result: 'ok',
          summary: {
            total_projects: all.length,
            active: active.length,
            overdue: overdue.length,
            completed: completed.length,
            total_revenue: totalRevenue,
            currency: 'USD',
          },
          projects: all.map((p: { id: string; client_name: string; project_type: string; budget: number; currency: string; status: string; deadline: string }) => ({
            id: p.id,
            client: p.client_name,
            type: p.project_type,
            budget: p.budget,
            currency: p.currency,
            status: p.status,
            deadline: p.deadline,
          })),
        });
      }

      case 'list_projects': {
        const statusFilter = searchParams.get('status');
        let query = supabase.from('projects').select('*').order('created_at', { ascending: false });
        if (statusFilter && statusFilter !== 'all') {
          query = query.eq('status', statusFilter);
        }
        const { data: projects } = await query;

        return NextResponse.json({
          result: 'ok',
          count: (projects ?? []).length,
          projects: (projects ?? []).map((p: { id: string; client_name: string; project_type: string; budget: number; currency: string; status: string; deadline: string }) => ({
            id: p.id,
            client: p.client_name,
            type: p.project_type,
            budget: p.budget,
            currency: p.currency,
            status: p.status,
            deadline: p.deadline,
          })),
        });
      }

      default:
        return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 400 });
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const action = body.action ?? 'search';

  try {
    switch (action) {
      case 'search_knowledge': {
        const query = body.query ?? '';
        if (!query) {
          return NextResponse.json({ error: 'Missing query' }, { status: 400 });
        }

        // Use TF-IDF search (same engine as the main app)
        const { searchKnowledge } = await import('@/lib/rag');
        const results = await searchKnowledge(query);

        return NextResponse.json({
          result: 'ok',
          query,
          count: results.length,
          results: results.map((r: { title: string; content: string; score?: number }) => ({
            title: r.title,
            content: r.content?.substring(0, 500) ?? '',
            score: r.score ?? 0,
          })),
        });
      }

      case 'create_project': {
        const { client_name, project_type, budget, currency, deadline } = body;
        if (!client_name || !project_type || budget == null || !deadline) {
          return NextResponse.json({ error: 'Missing required fields: client_name, project_type, budget, deadline' }, { status: 400 });
        }

        const supabase = createServiceClient();
        const projectId = `projects-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
        const { data, error } = await supabase.from('projects').insert({
          id: projectId,
          client_name,
          project_type,
          budget: Number(budget),
          currency: currency ?? 'USD',
          deadline,
          status: 'active',
          created_at: new Date().toISOString(),
        }).select().single();

        if (error) {
          return NextResponse.json({ error: error.message }, { status: 500 });
        }

        return NextResponse.json({
          result: 'ok',
          project: {
            id: projectId,
            client: client_name,
            type: project_type,
            budget: Number(budget),
            currency: currency ?? 'USD',
            deadline,
            status: 'active',
          },
        });
      }

      case 'generate_contract': {
        const { client_name, project_type, budget, currency, deadline } = body;
        if (!client_name || !project_type) {
          return NextResponse.json({ error: 'Missing required fields: client_name, project_type' }, { status: 400 });
        }

        // Generate a simple contract from template (no LLM needed)
        const contractText = [
          `工作合同 (Service Agreement)`,
          ``,
          `甲方 (Client): ${client_name}`,
          `乙方 (Contractor): Solo Worker`,
          ``,
          `1. 服务内容: ${project_type}`,
          `2. 合同金额: ${budget ?? 'TBD'} ${currency ?? 'USD'}`,
          `3. 交付日期: ${deadline ?? 'TBD'}`,
          `4. 付款条款: 50% 预付，50% 验收后付清`,
          `5. 知识产权: 交付物在尾款结清后归甲方所有`,
          `6. 逾期条款: 逾期 14 天加收 5% 滞纳金`,
          ``,
          `本合同自双方签字之日起生效。`,
        ].join('\n');

        return NextResponse.json({
          result: 'ok',
          contract: contractText,
        });
      }

      default:
        return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 400 });
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
