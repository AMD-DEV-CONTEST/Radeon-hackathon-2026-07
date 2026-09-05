import type { MilestoneView } from '../viewmodel/statusView';
import type { Milestone } from '../contracts/types';
import type { RelationDiscoveryView } from '../viewmodel/relationView';
import { MILESTONE_STATE_LABEL, MILESTONE_STATE_TONE } from '../components/labels';
import { Badge, type Tone } from '../components/primitives';
import { STAGES, type ShellView } from './stages';
import './shell.css';

/**
 * The relation gate is a backend rule, not a page: discovery stays locked
 * until M4 readiness is accepted, and the API answers 409 until then. It is
 * rendered between M4 and M5 so the rail shows why the flow pauses there.
 */
const GATE_PRESENTATION: Record<
  RelationDiscoveryView['gate'],
  { label: string; tone: Tone } | null
> = {
  LOCKED: { label: '已锁定', tone: 'warn' },
  READY: { label: '已就绪', tone: 'ok' },
  INVALIDATED: { label: '已失效', tone: 'danger' },
  NO_TRACE: null,
};


export function StageRail({
  activeView,
  onSelect,
  milestones,
  relation,
  onToggleCollapse,
}: {
  activeView: ShellView;
  onSelect: (view: ShellView) => void;
  milestones: MilestoneView[];
  relation?: RelationDiscoveryView | null;
  onToggleCollapse?: () => void;
}) {
  const stateOf = (milestone: Milestone | null) =>
    milestone === null ? null : (milestones.find((m) => m.milestone === milestone) ?? null);

  const gate = relation?.available ? GATE_PRESENTATION[relation.gate] : null;

  // Public progress uses the backend's own milestone basis only. It is a count
  // of confirmed milestones, never a percentage over internal work units.
  const confirmed = milestones.filter((m) => m.isConfirmed).length;

  return (
    <nav className="shell__rail" aria-label="页面" data-testid="shell-rail">
      <div className="shell__brand">
        <span className="shell__brand-mark" aria-hidden="true">
          ◆
        </span>
        <span className="shell__brand-text">
          <strong>Experience Asset Agent</strong>
          <small>把一段真实经历整理成可复用的经验资产</small>
        </span>
        <button
          type="button"
          className="shell__collapse"
          onClick={onToggleCollapse}
          data-testid="shell-collapse"
          aria-label="收起阶段轴"
          title="收起阶段轴"
        >
          ‹
        </button>
      </div>

      <ol className="shell__stages">
        {STAGES.map((stage) => {
          const milestone = stateOf(stage.milestone);
          const isActive = activeView === stage.id;
          return (
            <li key={stage.id}>
              <button
                type="button"
                className={`shell__stage${isActive ? ' shell__stage--active' : ''}${
                  milestone?.isCurrent ? ' shell__stage--current' : ''
                }`}
                onClick={() => onSelect(stage.id)}
                data-testid={`view-${stage.id}`}
                aria-current={isActive ? 'page' : undefined}
                title={milestone?.isCurrent ? '后端标记的当前里程碑' : undefined}
                data-current={milestone?.isCurrent ? 'true' : undefined}
              >
                <span className="shell__stage-icon" aria-hidden="true">
                  {stage.icon}
                </span>
                <span className="shell__stage-label">{stage.label}</span>
                {milestone ? (
                  <Badge tone={MILESTONE_STATE_TONE[milestone.state]}>
                    {MILESTONE_STATE_LABEL[milestone.state]}
                  </Badge>
                ) : null}
              </button>

              {stage.id === 'm4' && gate ? (
                <div className="shell__gate" data-testid="shell-relation-gate">
                  <span className="shell__gate-line" aria-hidden="true" />
                  <span className="shell__gate-label">关联经验</span>
                  <Badge tone={gate.tone}>{gate.label}</Badge>
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>

      <div className="shell__rail-foot">
        {milestones.length > 0 ? (
          <p className="shell__progress" data-testid="shell-progress">
            已确认 <strong>{confirmed}</strong> / {milestones.length} 个里程碑
          </p>
        ) : null}
        <p className="shell__rail-note">
          阶段状态来自后端里程碑依据，界面不推断进度。
          <br />
          <span className="shell__hint-keys">⌘/Ctrl + 1–6 切换阶段</span>
        </p>
      </div>
    </nav>
  );
}
