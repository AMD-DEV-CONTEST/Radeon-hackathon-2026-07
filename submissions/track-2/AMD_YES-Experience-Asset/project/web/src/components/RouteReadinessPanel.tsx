import type { RouteView } from '../viewmodel/statusView';
import { Badge, Panel } from './primitives';
import { ROUTE_ELIGIBILITY_LABEL, ROUTE_ELIGIBILITY_TONE, ROUTE_LABEL } from './labels';

export function RouteReadinessPanel({ routes }: { routes: RouteView[] }) {
  return (
    <Panel title="路线就绪度" testId="route-panel">
      <ul className="routes">
        {routes.map((r) => (
          <li key={r.route} className="route" data-testid={`route-${r.route}`}>
            <div className="route__head">
              <span className="route__name">{ROUTE_LABEL[r.route]}</span>
              <Badge
                tone={ROUTE_ELIGIBILITY_TONE[r.eligibility]}
                testId={`route-${r.route}-eligibility`}
                title={r.eligibility}
              >
                {ROUTE_ELIGIBILITY_LABEL[r.eligibility]}
              </Badge>
            </div>
            {r.explanation ? <p className="route__why">{r.explanation}</p> : null}
          </li>
        ))}
      </ul>
      <p className="hint">
        就绪度为占位展示：具体路线评估由 M5 策略层给出，界面不推断资格，也不代替审批。
      </p>
    </Panel>
  );
}
