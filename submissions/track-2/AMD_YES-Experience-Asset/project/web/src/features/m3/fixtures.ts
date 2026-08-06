import conflictingLedger from '../../../../contracts/examples/m3-ledger-conflicting.json';
import correctionLedger from '../../../../contracts/examples/m3-ledger-correction-invalidated.json';
import incompleteLedger from '../../../../contracts/examples/m3-ledger-incomplete.json';
import completeWorkspace from '../../../../contracts/examples/m3-workspace-complete.json';
import policyBlockedWorkspace from '../../../../contracts/examples/m3-workspace-policy-blocked.json';
import type { DecisionEvidenceLedgerV1, M3WorkspaceV1 } from './types';

function validatedWorkspace(value: unknown): M3WorkspaceV1 {
  if (!value || typeof value !== 'object') throw new Error('Invalid M3 fixture');
  const workspace = value as Record<string, unknown>;
  const artifact = workspace.artifact as Record<string, unknown> | undefined;
  if (!artifact || typeof artifact.artifact_id !== 'string' || !Array.isArray(artifact.entries)) {
    throw new Error('Invalid M3 fixture workspace');
  }
  return value as M3WorkspaceV1;
}

function validatedLedger(value: unknown): DecisionEvidenceLedgerV1 {
  if (!value || typeof value !== 'object') throw new Error('Invalid M3 ledger fixture');
  const ledger = value as Record<string, unknown>;
  if (typeof ledger.artifact_id !== 'string' || !Array.isArray(ledger.entries)) {
    throw new Error('Invalid M3 ledger fixture');
  }
  return value as DecisionEvidenceLedgerV1;
}

const complete = validatedWorkspace(completeWorkspace);

function workspaceWithArtifact(
  artifact: DecisionEvidenceLedgerV1,
  options: Partial<M3WorkspaceV1> = {},
): M3WorkspaceV1 {
  return {
    ...complete,
    artifact,
    history_artifact_ids: [artifact.artifact_id],
    progress: {
      ...complete.progress,
      last_durable_artifact_id: artifact.artifact_id,
    },
    ...options,
  };
}

export const M3_SCENARIOS: Record<string, M3WorkspaceV1> = {
  complete,
  incomplete: workspaceWithArtifact(
    validatedLedger(incompleteLedger),
  ),
  conflicting: workspaceWithArtifact(
    validatedLedger(conflictingLedger),
  ),
  correction_invalidation: workspaceWithArtifact(
    validatedLedger(correctionLedger),
    {
      is_current: false,
      allowed_actions: ['REGENERATE'],
    },
  ),
  permission_denied: validatedWorkspace(policyBlockedWorkspace),
};
