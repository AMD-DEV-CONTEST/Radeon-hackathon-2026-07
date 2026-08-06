import { useState } from 'react';
import { useStatus } from './hooks/useStatus';
import { Toolbar } from './components/Toolbar';
import { StatusDashboard } from './components/StatusDashboard';
import { ErrorScreen, LoadingScreen } from './components/StateScreens';
import { M1ExperienceWorkspace } from './features/m1/M1Workspace';
import { M2Workspace } from './features/m2/M2Workspace';
import { M3Workspace } from './features/m3/M3Workspace';
import { M4Workspace } from './features/m4/M4Workspace';
import { M5Workspace } from './features/m5/M5Workspace';
import { JourneyRail, JOURNEY_STEPS, type JourneyView } from './components/JourneyRail';

type AppView = JourneyView | 'status';

const STAGE_COPY: Record<JourneyView, { title: string; description: string }> = {
  m1: { title: 'Tell us what happened', description: 'No preparation needed. Share the experience in your own words and the agent will shape it into an editable brief.' },
  m2: { title: 'Find the moments that changed the outcome', description: 'Separate real turning points, obstacles, and decisive actions from ordinary events.' },
  m3: { title: 'Reconstruct why each decision made sense', description: 'Bring choices, evidence, alternatives, and outcomes back into one decision trail.' },
  m4: { title: 'Turn one experience into a reusable method', description: 'Define when the insight applies, where it fails, and only then connect it to prior experience.' },
  m5: { title: 'Create a delivery people can actually use', description: 'Choose an audience, review privacy, preview the result, and approve the final version.' },
};

export function App() {
  const { phase, view, error, config, refresh, isRefreshing } = useStatus();
  const [activeView, setActiveView] = useState<AppView>(() => {
    const requested = new URLSearchParams(window.location.search).get('view');
    return requested === 'status' ||
      requested === 'm1' ||
      requested === 'm2' ||
      requested === 'm3' ||
      requested === 'm4' ||
      requested === 'm5'
      ? requested
      : 'm1';
  });

  const selectView = (next: AppView) => {
    const url = new URL(window.location.href);
    url.searchParams.set('view', next);
    window.history.replaceState({}, '', url);
    setActiveView(next);
  };

  const activeJourneyView: JourneyView = activeView === 'status' ? 'm1' : activeView;
  const activeIndex = JOURNEY_STEPS.findIndex((step) => step.id === activeJourneyView);
  const stage = STAGE_COPY[activeJourneyView];

  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">Skip to workspace</a>
      <header className="app__header">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">EA</span>
          <div>
            <p className="eyebrow">Experience Asset Agent</p>
            <h1 className="app__title">Turn experience into reusable knowledge</h1>
          </div>
        </div>
        <div className="header-actions">
          <span className="service-pill"><i aria-hidden="true" /> Private & local</span>
          <span className="service-pill">Autosaved</span>
          <button
            type="button"
            className={`btn btn--utility${activeView === 'status' ? ' btn--primary' : ''}`}
            onClick={() => selectView(activeView === 'status' ? activeJourneyView : 'status')}
            data-testid="view-status"
          >
            {activeView === 'status' ? 'Back to journey' : 'System status'}
          </button>
        </div>
      </header>

      <div className="app-layout">
        <JourneyRail active={activeJourneyView} onSelect={selectView} />
        <main className="app__main" id="workspace">
          {activeView !== 'status' ? (
            <section className="stage-context" aria-labelledby="stage-heading">
              <div>
                <p className="eyebrow">Step {activeIndex + 1} of {JOURNEY_STEPS.length} · {JOURNEY_STEPS[activeIndex].artifact}</p>
                <h2 id="stage-heading">{stage.title}</h2>
                <p>{stage.description}</p>
              </div>
              <div className="stage-context__nav" aria-label="Journey navigation">
                <button className="btn" type="button" disabled={activeIndex === 0} onClick={() => selectView(JOURNEY_STEPS[activeIndex - 1].id)}>← Back</button>
                <button className="btn btn--primary" type="button" disabled={activeIndex === JOURNEY_STEPS.length - 1} onClick={() => selectView(JOURNEY_STEPS[activeIndex + 1].id)}>Continue →</button>
              </div>
              <p className="sr-only" role="status">Step {activeIndex + 1}: {stage.title}</p>
            </section>
          ) : (
            <section className="stage-context stage-context--status">
              <div><p className="eyebrow">Runtime evidence</p><h2>System status</h2><p>Inspect the local environment, milestones, and service health.</p></div>
            </section>
          )}
        {activeView === 'm5' ? (
          <M5Workspace apiBaseUrl={config.apiBaseUrl} onCanonicalEdit={() => selectView('m1')} />
        ) : activeView === 'm4' ? (
          <M4Workspace apiBaseUrl={config.apiBaseUrl} />
        ) : activeView === 'm3' ? (
          <M3Workspace apiBaseUrl={config.apiBaseUrl} />
        ) : activeView === 'm1' ? (
          <M1ExperienceWorkspace apiBaseUrl={config.apiBaseUrl} />
        ) : activeView === 'm2' ? (
          <M2Workspace apiBaseUrl={config.apiBaseUrl} />
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
        </main>
      </div>

      <footer className="app__footer">
        <span>Private by default · Recoverable versions · Explicit tool approval</span>
        <span>Contract source <code>contracts/openapi.json</code></span>
      </footer>
    </div>
  );
}

export default App;
