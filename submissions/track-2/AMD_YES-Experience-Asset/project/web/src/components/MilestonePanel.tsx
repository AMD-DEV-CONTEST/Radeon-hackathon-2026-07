import type { MilestoneView } from '../viewmodel/statusView';
import { Badge, Panel } from './primitives';
import { MILESTONE_STATE_LABEL, MILESTONE_STATE_TONE } from './labels';

export function MilestonePanel({ milestones }: { milestones: MilestoneView[] }) {
  return (
    <Panel title="里程碑状态" testId="milestone-panel">
      <ol className="milestones">
        {milestones.map((m) => (
          <li
            key={m.milestone}
            className={`milestone${m.isCurrent ? ' milestone--current' : ''}`}
            data-testid={`milestone-${m.milestone}`}
            data-state={m.state}
          >
            <span className="milestone__id">{m.milestone}</span>
            <Badge tone={MILESTONE_STATE_TONE[m.state]} testId={`milestone-${m.milestone}-state`}>
              {MILESTONE_STATE_LABEL[m.state]}
            </Badge>
            {m.isCurrent ? <span className="milestone__current-tag">当前</span> : null}
          </li>
        ))}
      </ol>
      <p className="hint">
        公开进度只使用后端提供的里程碑依据；内部工作单元不会被换算成百分比。
      </p>
    </Panel>
  );
}
