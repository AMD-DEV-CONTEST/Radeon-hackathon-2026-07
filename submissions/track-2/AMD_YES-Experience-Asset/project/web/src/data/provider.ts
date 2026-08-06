/**
 * The data-source seam.
 *
 * Both the mock provider and the live provider return the same `StatusSnapshot`
 * shape, so the UI switches between checked-in mocks and the localhost FastAPI
 * backend **without any UI contract change**. The snapshot only ever carries
 * contract-typed data (or an explicit "not available" marker); the UI never
 * invents backend state.
 */
import type {
  AgentRunStateV1,
  ExperienceAssetV1,
  HealthStatusV1,
  ProgressEventV1,
  RelationWorkspaceV1,
  RetrievalPhaseTraceV1,
  TerminalResultV1,
} from '../contracts/types';

/** Whether an Experience Asset instance is available to display. */
export type AssetAvailability =
  /** A canonical asset version is present. */
  | 'present'
  /** The backend is reachable but no asset has been created yet (empty state). */
  | 'none'
  /**
   * The aggregate live status provider does not compose asset/run state. The
   * M1–M5 product endpoints remain available separately. This marker prevents
   * the shell from fabricating a combined snapshot.
   */
  | 'not_served';

export type ActiveRun =
  | {
      readonly kind: 'progress';
      readonly event: ProgressEventV1;
      readonly state: AgentRunStateV1;
    }
  | { readonly kind: 'terminal'; readonly result: TerminalResultV1 };

export interface StatusSnapshot {
  readonly source: 'mock' | 'live';
  readonly scenario: string | null;
  readonly fetchedAt: string;
  /** null when the health endpoint could not be read (with `healthError` set). */
  readonly health: HealthStatusV1 | null;
  readonly healthError: string | null;
  readonly assetAvailability: AssetAvailability;
  readonly asset: ExperienceAssetV1 | null;
  /** Current run activity, or null when no run is active. */
  readonly activeRun: ActiveRun | null;
  /**
   * Frozen set of terminal-state names as reported by the backend contract
   * endpoint (`/api/v1/contracts/terminal-states`), when available. Used only
   * to prove the live contract surface, never to synthesize run state.
   */
  readonly terminalStates: readonly string[] | null;
  /**
   * Backend-owned retrieval-phase trace that gates cross-asset relation
   * discovery. `null` when the aggregate source does not compose it, so the
   * shell stays silent instead of fabricating a relation gate.
   */
  readonly retrievalTrace: RetrievalPhaseTraceV1 | null;
  /**
   * Read-only composition of relation state from the sidecar relation ledger.
   * Relation state deliberately does not travel on `asset`: the snapshot is
   * immutable and content-hashed, so carrying a confirmation there would append
   * a content version and change the hash, while the non-contamination
   * invariant requires it identical across a relation read.
   *
   * `null` when the source does not serve it, so the panel can say so instead
   * of fabricating a gate.
   */
  readonly relationWorkspace: RelationWorkspaceV1 | null;
}

/** A recoverable fetch failure. The UI shows a retry affordance. */
export class StatusFetchError extends Error {
  readonly retryable: boolean;
  constructor(message: string, options?: { retryable?: boolean; cause?: unknown }) {
    super(message, options?.cause !== undefined ? { cause: options.cause } : undefined);
    this.name = 'StatusFetchError';
    this.retryable = options?.retryable ?? true;
  }
}

export interface StatusProvider {
  readonly source: 'mock' | 'live';
  fetchStatus(signal?: AbortSignal): Promise<StatusSnapshot>;
}
