import type { StatusView } from '../viewmodel/statusView';
import { HealthPanel } from './HealthPanel';
import { VersionPanel } from './VersionPanel';
import { MilestonePanel } from './MilestonePanel';
import { CountsPanel } from './CountsPanel';
import { RouteReadinessPanel } from './RouteReadinessPanel';
import { RelationDiscoveryPanel } from './RelationDiscoveryPanel';
import { RunActivityPanel } from './RunActivityPanel';
import { StaleNotice } from './StaleNotice';
import { EmptyAssetScreen } from './StateScreens';

/**
 * Composes the status panels. Health always renders (it is available in every
 * source). Asset-derived panels render only when a canonical asset is present;
 * otherwise a truthful empty/not-served screen shows in their place.
 */
export function StatusDashboard({ view }: { view: StatusView }) {
  const hasAsset = view.version.present;
  return (
    <div className="dashboard" data-testid="status-dashboard" data-has-asset={hasAsset}>
      <HealthPanel health={view.health} />

      {hasAsset ? (
        <>
          <StaleNotice stale={view.stale} />
          <div className="grid">
            <VersionPanel version={view.version} />
            <RunActivityPanel run={view.run} />
            <MilestonePanel milestones={view.milestones} />
            {view.counts ? <CountsPanel counts={view.counts} /> : null}
            <RouteReadinessPanel routes={view.routes} />
            <RelationDiscoveryPanel relation={view.relation} />
          </div>
        </>
      ) : (
        <EmptyAssetScreen availability={view.version.availability} />
      )}
    </div>
  );
}
