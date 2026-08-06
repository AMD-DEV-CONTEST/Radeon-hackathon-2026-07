/**
 * Dashboard data cache layer
 * 
 * Uses in-memory cache with TTL to reduce database queries.
 * Cache is invalidated when:
 * - TTL expires (30 seconds)
 * - User explicitly refreshes
 * - Data mutation occurs (via invalidateDashboardCache)
 */

type DashboardData = {
  projects: Array<{
    id: string;
    client_name: string;
    project_type: string;
    status: string;
    budget: number | string;
    currency: string;
    deadline: string;
    created_at: string;
  }>;
  actions: Array<{
    id: string;
    action_type: string;
    project_id: string | null;
    payload: unknown;
    created_at: string;
  }>;
  payments: Array<{
    amount: number;
    currency: string;
    received_date: string;
    project_id: string;
  }>;
  deliverables: Array<{
    id: string;
    project_id: string;
    title: string;
    type: string;
    status: string;
    url: string | null;
    created_at: string;
  }>;
  cachedAt: number;
};

// In-memory cache with 30 second TTL
const CACHE_TTL = 30_000; // 30 seconds
let cache: DashboardData | null = null;
let cacheTimestamp = 0;

export function getCachedDashboardData(): DashboardData | null {
  if (!cache) return null;
  
  const now = Date.now();
  if (now - cacheTimestamp > CACHE_TTL) {
    cache = null;
    return null;
  }
  
  return cache;
}

export function setCachedDashboardData(data: Omit<DashboardData, 'cachedAt'>): void {
  cache = {
    ...data,
    cachedAt: Date.now(),
  };
  cacheTimestamp = Date.now();
}

export function invalidateDashboardCache(): void {
  cache = null;
  cacheTimestamp = 0;
}

export function getCacheAge(): number {
  if (!cache) return Infinity;
  return Date.now() - cacheTimestamp;
}

/**
 * Check if cache is fresh enough to use (within TTL)
 */
export function isCacheFresh(maxAge: number = CACHE_TTL): boolean {
  if (!cache) return false;
  return Date.now() - cacheTimestamp < maxAge;
}