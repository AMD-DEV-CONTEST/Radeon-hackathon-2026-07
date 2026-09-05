import type { CountsView } from '../viewmodel/statusView';
import { Panel } from './primitives';

function Stat({ label, value, testId }: { label: string; value: number; testId: string }) {
  return (
    <div className="stat" data-testid={testId}>
      <span className="stat__value">{value}</span>
      <span className="stat__label">{label}</span>
    </div>
  );
}

export function CountsPanel({ counts }: { counts: CountsView }) {
  return (
    <Panel title="陈述与未决项" testId="counts-panel">
      <div className="stats">
        <Stat label="材料陈述" value={counts.totalStatements} testId="count-total" />
        <Stat label="已确认" value={counts.confirmedStatements} testId="count-confirmed" />
        <Stat label="未解决陈述" value={counts.unresolvedStatements} testId="count-unresolved" />
        <Stat label="待回答问题" value={counts.openQuestions} testId="count-open-questions" />
      </div>
      <p className="hint">
        “已确认”仅统计确认状态为 CONFIRMED 的陈述；跳过或延后不计为已回答。
      </p>
    </Panel>
  );
}
