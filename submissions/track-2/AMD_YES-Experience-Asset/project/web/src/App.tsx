import { useCallback, useEffect, useState } from 'react';
import { useStatus } from './hooks/useStatus';
import { Toolbar } from './components/Toolbar';
import { StatusDashboard } from './components/StatusDashboard';
import { ErrorScreen, LoadingScreen } from './components/StateScreens';
import { M1ExperienceWorkspace } from './features/m1/M1Workspace';
import { M2Workspace } from './features/m2/M2Workspace';
import { M3Workspace } from './features/m3/M3Workspace';
import { M4Workspace } from './features/m4/M4Workspace';
import { M5Workspace } from './features/m5/M5Workspace';
import { StageRail } from './shell/StageRail';
import { GlobalStatus } from './shell/GlobalStatus';
import { StageAdvance } from './shell/StageAdvance';
import { STAGES, type ShellView } from './shell/stages';

const SHORTCUT_ORDER = STAGES.map((stage) => stage.id);

export function App() {
  const { phase, view, error, config, refresh, isRefreshing } = useStatus();
  const [activeView, setActiveView] = useState<ShellView>(() => {
    const requested = new URLSearchParams(window.location.search).get('view');
    return requested === 'm1' ||
      requested === 'm2' ||
      requested === 'm3' ||
      requested === 'm4' ||
      requested === 'm5'
      ? requested
      : 'status';
  });
  const [railCollapsed, setRailCollapsed] = useState(false);

  const selectView = useCallback((next: ShellView) => {
    const url = new URL(window.location.href);
    if (next !== 'status') url.searchParams.set('view', next);
    else url.searchParams.delete('view');
    window.history.replaceState({}, '', url);
    setActiveView(next);
  }, []);

  /*
   * Stage shortcuts. Modifier-qualified so they cannot fire while someone is
   * typing an experience into a field, and ignored entirely when the browser
   * is already using the chord for something else via alt/shift.
   */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
      const index = Number(event.key) - 1;
      const target = SHORTCUT_ORDER[index];
      if (!target) return;
      event.preventDefault();
      selectView(target);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [selectView]);

  return (
    <div className={`shell${railCollapsed ? ' shell--rail-collapsed' : ''}`}>
      {railCollapsed ? (
        <button
          type="button"
          className="shell__rail-restore"
          onClick={() => setRailCollapsed(false)}
          data-testid="shell-expand"
          aria-label="展开阶段轴"
          title="展开阶段轴"
        >
          ›
        </button>
      ) : (
        <StageRail
          activeView={activeView}
          onSelect={selectView}
          milestones={view?.milestones ?? []}
          relation={view?.relation ?? null}
          onToggleCollapse={() => setRailCollapsed(true)}
        />
      )}

      <div className="shell__body">
      <GlobalStatus view={view ?? null} />

      <main className="shell__main">
        {activeView === 'm5' ? (
          <M5Workspace
            apiBaseUrl={config.apiBaseUrl}
            onCanonicalEdit={() => selectView('m1')}
            onStatusChange={refresh}
          />
        ) : activeView === 'm4' ? (
          <M4Workspace apiBaseUrl={config.apiBaseUrl} onStatusChange={refresh} />
        ) : activeView === 'm3' ? (
          <M3Workspace apiBaseUrl={config.apiBaseUrl} onStatusChange={refresh} />
        ) : activeView === 'm1' ? (
          <M1ExperienceWorkspace apiBaseUrl={config.apiBaseUrl} onStatusChange={refresh} />
        ) : activeView === 'm2' ? (
          <M2Workspace apiBaseUrl={config.apiBaseUrl} onStatusChange={refresh} />
        ) : (
          <>
            <Toolbar
              config={config}
              onRefresh={refresh}
              isRefreshing={isRefreshing}
              fetchedAt={view?.fetchedAt ?? null}
            />
            {phase === 'loading' ? <LoadingScreen /> : null}
            {phase === 'error' && error ? (
              <ErrorScreen
                message={error.message}
                retryable={error.retryable}
                onRetry={refresh}
              />
            ) : null}
            {phase === 'ready' && view ? <StatusDashboard view={view} /> : null}
          </>
        )}
        <StageAdvance
          activeView={activeView}
          milestones={view?.milestones ?? []}
          relation={view?.relation ?? null}
          onSelect={selectView}
        />
      </main>

      <footer className="shell__footer">
        <span>
          本地优先 · 合同源 <code>contracts/openapi.json</code> ·
          来源说明 <code>web/contracts/PROVENANCE.md</code>
        </span>
      </footer>
      </div>
    </div>
  );
}

export default App;
