export type M1SourceKind =
  | 'CONVERSATION'
  | 'PASTED_TEXT'
  | 'TXT_FILE'
  | 'MD_FILE'
  | 'ADAPTED_PUBLIC_FIXTURE';

export interface M1IngestRequest {
  source_kind: M1SourceKind;
  text: string;
  display_label: string;
  original_file_name?: string;
  goal_hint?: string;
}

export interface ExperienceBriefV1 {
  schema_version: '0.1.0';
  context: string;
  goal: string;
  constraints: string[];
  user_intent: string;
  source_boundary: string;
  source_ids: string[];
  statement_ids: string[];
  confirmed_statement_count: number;
  unresolved_question_count: number;
}

export interface M1Question {
  question_id: string;
  question: string;
  why_it_matters: string;
  state: 'OPEN' | 'DEFERRED';
}

export interface M1Workspace {
  asset: {
    asset_id: string;
    version_id: string;
    lifecycle: 'ACTIVE' | 'PAUSED';
    current_milestone: string;
    milestone_states: Record<string, string>;
    derivation_metadata: Record<string, unknown>;
  };
  brief: ExperienceBriefV1;
  questions: M1Question[];
  progress: {
    artifact_state: string;
    confirmed_statement_count: number;
    unresolved_question_count: number;
    saved_version_id: string;
    autosave_state: 'SAVED';
    last_saved_at: string;
  };
  progress_event: {
    stage: string;
    state: string;
    message: string;
  };
  terminal_state: string;
  latest_agent_run: {
    run_id: string;
    model_id: string;
    server_base_url: string;
    retrieval_scope: string;
    work_plan: {
      goal: string;
      revision: number;
      steps: Array<{
        step_id: string;
        step_kind: string;
        reason: string;
        status: string;
        stop_condition: string;
      }>;
    };
    retrieved_evidence: Array<{
      retrieval_id: string;
      provenance_ref: string;
      content_hash: string;
      no_match: boolean;
    }>;
    tool_proposals: Array<{
      name: string;
      permission_granted: false;
    }>;
    policy_decisions: Array<{
      outcome: 'ALLOW' | 'DENY';
      reason_codes: string[];
    }>;
    tool_executions: Array<{
      tool_name: string;
      status: string;
      observation_refs: string[];
    }>;
    verification_report: {
      outcome: string;
      checks: Record<string, boolean>;
      finding_codes: string[];
      safe_summary: string;
    } | null;
    terminal_state: string | null;
  } | null;
  allowed_actions: string[];
}

export interface M1Draft {
  context: string;
  goal: string;
  constraints: string;
  userIntent: string;
}

export function draftFromWorkspace(workspace: M1Workspace): M1Draft {
  return {
    context: workspace.brief.context,
    goal: workspace.brief.goal,
    constraints: workspace.brief.constraints.join('\n'),
    userIntent: workspace.brief.user_intent,
  };
}

export function draftMatchesWorkspace(draft: M1Draft, workspace: M1Workspace): boolean {
  const normalizedConstraints = draft.constraints
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);
  return (
    draft.context === workspace.brief.context &&
    draft.goal === workspace.brief.goal &&
    draft.userIntent === workspace.brief.user_intent &&
    JSON.stringify(normalizedConstraints) === JSON.stringify(workspace.brief.constraints)
  );
}
