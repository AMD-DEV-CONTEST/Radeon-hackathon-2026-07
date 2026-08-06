import type { SupabaseClient } from '@supabase/supabase-js';
import { STAGE_ORDER, type ChecksMap } from './workflow';

/**
 * Maps a project status to the minimum workflow stage that should be active.
 * Returns null if the status doesn't map to a workflow stage.
 *
 * active    → null  (stays in whatever stage it's in — could be kickoff or in_progress)
 * delivered → 'delivery'
 * invoiced  → 'invoiced'
 * paid      → 'paid'
 */
function statusToMinStage(status: string): string | null {
  switch (status) {
    case 'delivered': return 'delivery';
    case 'invoiced':  return 'invoiced';
    case 'paid':     return 'paid';
    default:         return null;
  }
}

/**
 * Auto-marks workflow checks based on the action that just occurred.
 * This ensures the workflow tracker reflects reality without manual toggling.
 */
function autoChecksForStage(stage: string): Partial<ChecksMap> {
  const checks: Partial<ChecksMap> = {};
  switch (stage) {
    case 'invoiced':
      checks['invoiced:invoice_sent'] = true;
      checks['invoiced:payment_terms_set'] = true;
      break;
    case 'paid':
      checks['paid:payment_received'] = true;
      break;
  }
  return checks;
}

/**
 * Syncs the workflow_steps row for a project when a tool changes its status.
 *
 * - If no workflow_steps row exists, creates one with the appropriate stage.
 * - If the target stage is ahead of the current stage, advances to it.
 * - Auto-marks relevant checks for the target stage.
 *
 * This function is non-blocking: it swallows errors so tool execution
 * is never broken by a workflow sync failure.
 */
export async function syncWorkflowForProject(
  supabase: SupabaseClient,
  projectId: string,
  newStatus: string,
): Promise<void> {
  try {
    const targetStage = statusToMinStage(newStatus);
    if (!targetStage) return; // status doesn't map to a stage change

    const targetIdx = STAGE_ORDER.indexOf(targetStage);

    // Load existing workflow row
    const { data: existing } = await supabase
      .from('workflow_steps')
      .select('*')
      .eq('project_id', projectId)
      .maybeSingle();

    let currentStage = existing?.stage ?? 'kickoff';
    let checks: ChecksMap = (existing?.checks as ChecksMap) ?? {};

    // Only advance — never go backwards
    const currentIdx = STAGE_ORDER.indexOf(currentStage);
    if (targetIdx <= currentIdx) {
      // Already at or past the target stage — just update checks
      Object.assign(checks, autoChecksForStage(targetStage));
    } else {
      // Advance to target stage
      currentStage = targetStage;
      Object.assign(checks, autoChecksForStage(targetStage));
    }

    await supabase
      .from('workflow_steps')
      .upsert(
        { project_id: projectId, stage: currentStage, checks },
        { onConflict: 'project_id' },
      );
  } catch {
    // Non-blocking: workflow sync failure must never break the tool
  }
}

/**
 * Creates an initial workflow_steps row for a newly created project.
 * Called by the create_project tool handler.
 */
export async function initWorkflowForProject(
  supabase: SupabaseClient,
  projectId: string,
): Promise<void> {
  try {
    await supabase
      .from('workflow_steps')
      .upsert(
        { project_id: projectId, stage: 'kickoff', checks: {} },
        { onConflict: 'project_id' },
      );
  } catch {
    // Non-blocking
  }
}

/**
 * Marks a specific workflow check as complete for a project.
 * Used when a tool performs an action that satisfies a checklist item.
 */
export async function markWorkflowCheck(
  supabase: SupabaseClient,
  projectId: string,
  checkKey: string,
): Promise<void> {
  try {
    const { data: existing } = await supabase
      .from('workflow_steps')
      .select('*')
      .eq('project_id', projectId)
      .maybeSingle();

    const stage = existing?.stage ?? 'kickoff';
    const checks: ChecksMap = (existing?.checks as ChecksMap) ?? {};
    checks[checkKey] = true;

    await supabase
      .from('workflow_steps')
      .upsert(
        { project_id: projectId, stage, checks },
        { onConflict: 'project_id' },
      );
  } catch {
    // Non-blocking
  }
}
