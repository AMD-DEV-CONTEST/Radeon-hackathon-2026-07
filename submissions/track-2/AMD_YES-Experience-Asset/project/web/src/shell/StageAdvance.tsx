import type { MilestoneView } from '../viewmodel/statusView';
import type { RelationDiscoveryView } from '../viewmodel/relationView';
import { STAGES, type ShellView } from './stages';
import './shell.css';

/**
 * The flow is gated: the backend refuses to generate a milestone until its
 * upstream is confirmed. That rule was only visible as a rejected request
 * after the fact. State it up front, and once the gate is actually open, offer
 * the step rather than making the user find it in the rail.
 *
 * Readiness comes from backend milestone state plus the explicit M4 Knowledge
 * Card relation gate. This never confirms anything itself and never claims a
 * gate is open that the API would refuse.
 */
export function StageAdvance({
  activeView,
  milestones,
  relation,
  onSelect,
}: {
  activeView: ShellView;
  milestones: MilestoneView[];
  relation?: RelationDiscoveryView | null;
  onSelect: (view: ShellView) => void;
}) {
  const index = STAGES.findIndex((stage) => stage.id === activeView);
  const current = STAGES[index];
  const next = STAGES[index + 1];

  // The status view is not part of the chain, and M5 has nothing after it.
  if (!current?.milestone || !next?.milestone) return null;

  const state = milestones.find((m) => m.milestone === current.milestone);
  if (!state) return null;

  const waitingForKnowledgeCard =
    current.id === 'm4' && !(relation?.available === true && relation.gate === 'READY');
  const open = state.isConfirmed && !waitingForKnowledgeCard;

  return (
    <div className="shell__advance" data-testid="shell-advance">
      {open ? (
        <>
          <span className="shell__advance-text">
            {current.milestone} 已确认，可以进入下一阶段。
          </span>
          <button
            type="button"
            className="btn btn--primary"
            data-testid="shell-advance-go"
            onClick={() => onSelect(next.id)}
          >
            进入 {next.label} →
          </button>
        </>
      ) : waitingForKnowledgeCard ? (
        <span className="shell__advance-text shell__advance-text--muted">
          接受 M4 Knowledge Card 后才能进入 M5；确认 M4 产物本身不会绕过就绪门禁。
        </span>
      ) : (
        <span className="shell__advance-text shell__advance-text--muted">
          确认 {current.milestone} 后才能生成 {next.milestone}——后端会拒绝更早的请求。
        </span>
      )}
    </div>
  );
}
