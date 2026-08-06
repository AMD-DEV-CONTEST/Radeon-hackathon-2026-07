import { NextResponse } from 'next/server';
import { createServerClient } from '@/lib/supabase-server';
import { getCachedDashboardData, setCachedDashboardData, getCacheAge } from '@/lib/dashboard-cache';

export const dynamic = 'force-dynamic';

/**
 * GET /api/dashboard
 * 
 * Returns cached dashboard data if fresh (< 30s old),
 * otherwise fetches from database and updates cache.
 * 
 * Query params:
 * - force=1 - Bypass cache and fetch fresh data
 */
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const force = searchParams.get('force') === '1';
  
  // Return cached data if fresh (unless force refresh)
  if (!force) {
    const cached = getCachedDashboardData();
    if (cached) {
      return NextResponse.json({
        ...cached,
        fromCache: true,
        cacheAge: getCacheAge(),
      });
    }
  }
  
  // Fetch fresh data from database
  const supabase = createServerClient();
  
  const [
    { data: projects, error: projectsError },
    { data: actions, error: actionsError },
    { data: payments, error: paymentsError },
    { data: deliverables, error: deliverablesError },
  ] = await Promise.all([
    supabase.from('projects').select('id, client_name, project_type, status, budget, currency, deadline, created_at').order('created_at', { ascending: false }).limit(50),
    supabase.from('agent_actions').select('id, action_type, project_id, payload, created_at').order('created_at', { ascending: false }).limit(8),
    supabase.from('payments').select('amount, currency, received_date, project_id').order('received_date', { ascending: false }).limit(50),
    supabase.from('deliverables').select('id, project_id, title, type, status, url, created_at').order('created_at', { ascending: false }).limit(5),
  ]);
  
  if (projectsError || actionsError || paymentsError || deliverablesError) {
    return NextResponse.json(
      { error: 'Failed to fetch dashboard data' },
      { status: 500 }
    );
  }
  
  const data = {
    projects: projects ?? [],
    actions: actions ?? [],
    payments: payments ?? [],
    deliverables: deliverables ?? [],
  };
  
  // Update cache
  setCachedDashboardData(data);
  
  return NextResponse.json({
    ...data,
    fromCache: false,
    cacheAge: 0,
  });
}