import { startTransition, useEffect, useState } from "react";
import { getCatalog, getConfig, getFinancials, getGoldenCase, getPeerEvaluations } from "./api";
import { CaseNotes, InsightPanel } from "./components/InsightPanel";
import { MobileHeader, Navigation } from "./components/Navigation";
import { ProofDrawer } from "./components/ProofDrawer";
import { IntelligenceDrawer } from "./components/IntelligenceDrawer";
import { LiveExecutionPlan } from "./components/LiveExecutionPlan";
import { RunProgress } from "./components/RunProgress";
import { ScenarioBar } from "./components/ScenarioBar";
import { ResearchScope } from "./components/ResearchScope";
import { ArrowIcon, ChipIcon, ShieldIcon, SparkIcon } from "./components/Icons";
import { MemoryControls } from "./components/CaseLibrary";
import { useResearchRun } from "./hooks/useResearchRun";
import { displayCaseTitle, displayCompany } from "./format";
import type { FinancialSummary, PeerEvaluationSuite, ProductCatalog, Projection, ScenarioControl, WorkspaceConfig } from "./types";

const fallbackScenario: ScenarioControl = { rates: "higher_for_longer", ai_spending: "slower" };

export function App() {
  const [fixture, setFixture] = useState<Projection | null>(null);
  const [config, setConfig] = useState<WorkspaceConfig | null>(null);
  const [catalog, setCatalog] = useState<ProductCatalog | null>(null);
  const [financials, setFinancials] = useState<FinancialSummary | null>(null);
  const [peerEvaluations, setPeerEvaluations] = useState<PeerEvaluationSuite | null>(null);
  const [bootError, setBootError] = useState(false);
  const [question, setQuestion] = useState("");
  const [scenario, setScenario] = useState<ScenarioControl>(fallbackScenario);
  const [activeSection, setActiveSection] = useState("");
  const [navOpen, setNavOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTab, setDrawerTab] = useState<"evidence" | "calculations">("evidence");
  const [drawerRefs, setDrawerRefs] = useState<string[]>([]);
  const [followUp, setFollowUp] = useState("");
  const [retain, setRetain] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [intelligenceOpen, setIntelligenceOpen] = useState(false);
  const research = useResearchRun(fixture);

  useEffect(() => {
    let active = true;
    Promise.all([getGoldenCase(), getConfig(), getCatalog(), getFinancials(), getPeerEvaluations()]).then(([nextFixture, nextConfig, nextCatalog, nextFinancials, nextPeers]) => {
      if (!active) return;
      startTransition(() => {
        setFixture(nextFixture);
        setConfig(nextConfig);
        setCatalog(nextCatalog);
        setFinancials(nextFinancials);
        setPeerEvaluations(nextPeers);
        setQuestion(nextFixture.question);
        setScenario(nextConfig.scenario_defaults);
        setActiveSection(nextFixture.sections[0]?.section_type ?? "");
      });
    }).catch(() => setBootError(true));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (research.projection && !research.projection.sections.some((section) => section.section_type === activeSection)) {
      setActiveSection(research.projection.sections[0]?.section_type ?? "");
    }
  }, [research.projection, activeSection]);

  useEffect(() => {
    function closeOverlay(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setDrawerOpen(false);
      setNavOpen(false);
      setLibraryOpen(false);
      setIntelligenceOpen(false);
    }
    window.addEventListener("keydown", closeOverlay);
    return () => window.removeEventListener("keydown", closeOverlay);
  }, []);

  if (bootError) return <BootFailure />;
  const projection = research.projection ?? fixture;
  if (!projection || !config || !catalog || !financials || !peerEvaluations) return <BootScreen />;

  function openProof(tab: "evidence" | "calculations", refs: string[] = []) {
    setDrawerTab(tab);
    setDrawerRefs(refs ?? []);
    setDrawerOpen(true);
  }

  function submitFollowUp(questionText: string) {
    const clean = questionText.trim();
    if (!clean || !config?.follow_ups_live) return;
    setFollowUp("");
    void research.askFollowUp(clean, retain);
  }

  return (
    <div className="app-shell">
      <MobileHeader onOpen={() => setNavOpen(true)} />
      <Navigation projection={projection} activeSection={activeSection} open={navOpen} onOpen={() => setNavOpen(true)} onClose={() => setNavOpen(false)} onSection={setActiveSection} />
      <main className="research-main">
        <header className="case-topbar">
          <div className="case-title">
            <span className="status-pulse" />
            <div><span>Research case · {projection.intent.replaceAll("_", " ")}</span><strong>{displayCaseTitle(projection.title)}</strong></div>
          </div>
          <div className="runtime-badge"><ChipIcon /><span><strong>Local inference</strong>{projection.execution.runtime_label}</span></div>
        </header>

        <div className="research-canvas">
          <ResearchScope
            catalog={catalog}
            financials={financials}
            peers={peerEvaluations}
            scenario={scenario}
            live={config.mode === "live"}
            onQuestion={setQuestion}
          />
          <ScenarioBar question={question} scenario={scenario} running={research.running} onQuestion={setQuestion} onScenario={setScenario} onRun={() => void research.start(question, scenario, retain)} />
          <MemoryControls
            available={config.retention_available}
            retain={retain}
            retention={research.run?.retention}
            open={libraryOpen}
            onRetain={setRetain}
            onOpen={() => setLibraryOpen(true)}
            onClose={() => setLibraryOpen(false)}
            onLoad={(stored) => {
              research.loadProjection(stored);
              setQuestion(stored.question);
              setActiveSection(stored.sections[0]?.section_type ?? "");
            }}
          />
          {research.error && <div className="degraded-banner" role="alert"><ShieldIcon /><span><strong>Fail-safe state</strong>{research.error}</span></div>}
          {research.executionPlan ?? projection.execution_plan
            ? <LiveExecutionPlan
                plan={research.executionPlan ?? projection.execution_plan ?? null}
                traceID={research.run?.trace_id}
                running={research.running}
                connection={research.executionConnection}
                onProof={(refs) => openProof("evidence", refs)}
                onCalculations={(refs) => openProof("calculations", refs)}
                onLineage={() => setIntelligenceOpen(true)}
              />
            : <RunProgress events={research.events} running={research.running} />}

          <section className="case-overview" aria-label="Case overview">
            <div><span className="eyebrow">Companies</span><strong>{projection.companies.map((company) => displayCompany(company.label)).join(" × ")}</strong></div>
            <div><span className="eyebrow">Evidence coverage</span><strong>{Math.round(projection.metrics.evidence_coverage * 100)}%</strong></div>
            <div><span className="eyebrow">Supported context claims</span><strong>{projection.metrics.supported_claims} / {projection.metrics.claims}</strong></div>
            <button onClick={() => openProof("evidence")}><span className="eyebrow">Audit trail</span><strong>Open proof layer <ArrowIcon /></strong></button>
            <button onClick={() => setIntelligenceOpen(true)} disabled={!config.intelligence_audit}><span className="eyebrow">Intelligence path</span><strong>Inspect orchestration <ArrowIcon /></strong></button>
          </section>

          <InsightPanel projection={projection} activeSection={activeSection} onSection={setActiveSection} onProof={openProof} />
          <CaseNotes projection={projection} />
          <FollowUpPanel projection={projection} enabled={config.follow_ups_live} value={followUp} running={research.running} onValue={setFollowUp} onSubmit={submitFollowUp} />
        </div>
        <footer className="site-footer"><span>SignalForge · Private investor intelligence</span><span><ShieldIcon /> AI research can be inaccurate. Verify evidence and deterministic receipts before acting.</span></footer>
      </main>
      <ProofDrawer projection={projection} open={drawerOpen} tab={drawerTab} refs={drawerRefs} onTab={setDrawerTab} onClose={() => setDrawerOpen(false)} />
      <IntelligenceDrawer
        runID={projection.run_id}
        traceID={research.run?.run_id === projection.run_id ? research.run.trace_id : undefined}
        open={intelligenceOpen}
        protectedCapture={config.protected_capture}
        onClose={() => setIntelligenceOpen(false)}
      />
    </div>
  );
}

function FollowUpPanel({ projection, enabled, value, running, onValue, onSubmit }: { projection: Projection; enabled: boolean; value: string; running: boolean; onValue: (value: string) => void; onSubmit: (value: string) => void }) {
  return (
    <section className="follow-up-panel" aria-labelledby="follow-up-title">
      <div className="follow-up-heading"><SparkIcon /><div><span className="eyebrow">Case-aware follow-up</span><h2 id="follow-up-title">Push the thesis further.</h2></div></div>
      <div className="suggestion-row">
        {projection.follow_up_suggestions.map((suggestion) => <button key={suggestion.suggestion_id} onClick={() => enabled ? onSubmit(suggestion.question) : onValue(suggestion.question)} disabled={running}>{suggestion.label}<ArrowIcon /></button>)}
      </div>
      <form onSubmit={(event) => { event.preventDefault(); onSubmit(value); }}>
        <input value={value} onChange={(event) => onValue(event.target.value)} placeholder="Ask about evidence, assumptions, or thesis risks" maxLength={1200} aria-label="Follow-up question" />
        <button disabled={!enabled || running || value.trim().length === 0} aria-label="Submit follow-up"><ArrowIcon /></button>
      </form>
      {!enabled && <p className="mode-note"><ChipIcon /> Follow-up inference activates in live Radeon mode. Suggestions remain available as a demo of the intended flow.</p>}
    </section>
  );
}

function BootScreen() {
  return <div className="boot-screen"><span className="forge-loader"><i /><i /><i /></span><strong>Preparing the research workspace</strong><small>Loading the privacy-safe case projection</small></div>;
}

function BootFailure() {
  return <div className="boot-screen failure" role="alert"><ShieldIcon /><strong>The workspace stopped safely.</strong><small>Start the local SignalForge server, then reload this page.</small></div>;
}
