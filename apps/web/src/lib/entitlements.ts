/**
 * Subscription entitlements from /api/v1/auth/me
 */
export type SubscriptionTier = 'free' | 'pro' | 'creator'

export interface PlanLimits {
  storage_bytes: number
  training_local_monthly: number
  training_qualia_monthly: number
  training_concurrent_max: number
  skill_runs_monthly: number
  inference_priority: number
  qualia_max_hours: number
  workflow_nodes: string[]
  verbs: string[]
  can_publish_paid_skills: boolean
  commercial_license: boolean
  batch_jobs: boolean
  show_legacy_workflow_nodes: boolean
}

export interface Entitlements {
  tier: SubscriptionTier
  display_name: string
  tier_expires_at: string | null
  limits: PlanLimits
}

const TIER_RANK: Record<SubscriptionTier, number> = {
  free: 0,
  pro: 1,
  creator: 2,
}

export function tierAtLeast(current: SubscriptionTier, required: SubscriptionTier): boolean {
  return TIER_RANK[current] >= TIER_RANK[required]
}

export function canUseWorkflowNode(ent: Entitlements | null | undefined, nodeType: string): boolean {
  if (!ent) return false
  return ent.limits.workflow_nodes.includes(nodeType)
}

export function requiredTierForNode(nodeType: string): SubscriptionTier {
  if (nodeType === 'camera_denoise' || nodeType === 'trajectory_optimize') return 'pro'
  return 'pro'
}

export interface PlansCatalog {
  plans: Array<{ tier: string; display_name: string; limits: PlanLimits }>
  pricing: { pro_usd_monthly: number; pro_cny_monthly: number; creator_cny_monthly: number }
}

export async function fetchPlansCatalog(): Promise<PlansCatalog> {
  const r = await fetch('/api/v1/auth/plans')
  if (!r.ok) throw new Error(`plans ${r.status}`)
  return (await r.json()) as PlansCatalog
}
