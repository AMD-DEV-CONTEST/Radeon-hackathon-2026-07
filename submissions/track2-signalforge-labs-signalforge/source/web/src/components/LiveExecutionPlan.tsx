import { useEffect, useMemo, useState, type CSSProperties, type KeyboardEvent } from "react";
import {
  buildExecutionPresentation,
  humanize,
  type ChecklistPresentation,
  type ExecutionPresentation,
  type PhasePresentation,
  type StepPresentation
} from "../executionPresentation";
import type { ExecutionPlan, ExecutionStatus } from "../types";
import { CheckIcon, ChipIcon, ShieldIcon, SparkIcon } from "./Icons";

type Props = {
  plan: ExecutionPlan | null;
  traceID?: string;
  running: boolean;
  connection?: "idle" | "live" | "recovering" | "unavailable";
  onProof: (refs: string[]) => void;
  onCalculations: (refs: string[]) => void;
  onLineage: () => void;
};

type ExpansionState = {
  phases: Set<string>;
  steps: Set<string>;
  checks: Set<string>;
};

type ToolActivity = {
  sourceStepID: string;
  sourceStepLabel: string;
  item: ChecklistPresentation;
};

const terminalStatuses = new Set<ExecutionStatus>([
  "passed", "failed", "degraded", "skipped", "cancelled", "withheld", "unavailable"
]);

export function LiveExecutionPlan({
  plan,
  traceID,
  running,
  connection = "live",
  onProof,
  onCalculations,
  onLineage
}: Props) {
  const presentation = useMemo(
    () => plan ? buildExecutionPresentation(plan) : null,
    [plan]
  );
  const [expanded, setExpanded] = useState<ExpansionState>(emptyExpansion);
  const [followActive, setFollowActive] = useState(true);
  const [showLimitations, setShowLimitations] = useState(false);

  useEffect(() => {
    if (!presentation) {
      setExpanded(emptyExpansion());
      return;
    }
    setExpanded(defaultExpansion(presentation));
    setFollowActive(true);
    setShowLimitations(false);
  }, [presentation?.runID]);

  useEffect(() => {
    if (!presentation || !followActive) return;
    setExpanded((current) => mergeActiveExpansion(current, presentation));
  }, [followActive, presentation?.projectionSHA256]);

  if (!presentation) return null;

  const visiblePhases = showLimitations
    ? presentation.phases.filter((phase) => phase.attention)
    : presentation.phases;
  const toolActivities = collectToolActivities(presentation);

  const expandAll = () => {
    setExpanded({
      phases: new Set(presentation.phases.map((phase) => phase.id)),
      steps: new Set(presentation.phases.flatMap((phase) => phase.steps.map((step) => step.id))),
      checks: new Set(presentation.phases.flatMap((phase) =>
        phase.steps.flatMap((step) => step.checklist.map((item) => checkKey(step.id, item.id)))
      ))
    });
  };
  const collapseAll = () => {
    setFollowActive(false);
    setExpanded(emptyExpansion());
  };
  const togglePhase = (id: string, open: boolean) =>
    setExpanded((current) => ({ ...current, phases: toggleID(current.phases, id, open) }));
  const toggleStep = (id: string, open: boolean) =>
    setExpanded((current) => ({ ...current, steps: toggleID(current.steps, id, open) }));
  const toggleCheck = (id: string, open: boolean) =>
    setExpanded((current) => ({ ...current, checks: toggleID(current.checks, id, open) }));

  return (
    <section className={`execution-plan plan-${presentation.status}`} aria-labelledby="execution-plan-title">
      <header className="execution-plan-header" aria-live="polite">
        <div
          className="execution-progress-dial"
          style={{ "--plan-progress": `${presentation.percentage * 3.6}deg` } as CSSProperties}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={presentation.percentage}
          aria-valuetext={`${presentation.terminalSteps} of ${presentation.totalSteps} planned steps closed`}
          aria-label={`${presentation.percentage}% ${presentation.status === "passed" ? "complete" : "closed"}`}
        >
          <span>{presentation.percentage}</span><small>%</small>
        </div>
        <div className="execution-plan-heading">
          <span className="eyebrow">Live research execution</span>
          <h2 id="execution-plan-title">{presentation.headline}</h2>
          <p>Follow real work from a concise summary into bounded detail and verifiable proof.</p>
        </div>
        <div className="execution-plan-stats">
          <span><strong>{presentation.terminalSteps}</strong> / {presentation.totalSteps} closed</span>
          <span><strong>{presentation.maxParallelSpecialists}</strong> parallel specialists</span>
          {presentation.currentWave && <span><strong>{presentation.currentWave}</strong> active wave</span>}
          <span className={`execution-status status-${presentation.status}`}>{presentation.statusLabel}</span>
          {(connection === "recovering" || connection === "unavailable") && (
            <span className="execution-status status-unavailable" role="status">Reconnecting to signed plan</span>
          )}
        </div>
      </header>

      <div className="execution-plan-controls" aria-label="Execution disclosure controls">
        <div>
          <button type="button" onClick={expandAll}>Expand all</button>
          <button type="button" onClick={collapseAll}>Collapse all</button>
        </div>
        <div>
          <button
            type="button"
            aria-pressed={followActive}
            onClick={() => setFollowActive((current) => !current)}
          >
            Follow active
          </button>
          <button
            type="button"
            aria-pressed={showLimitations}
            onClick={() => setShowLimitations((current) => !current)}
          >
            Show limitations
            {presentation.limitations.length > 0 && <span>{presentation.limitations.length}</span>}
          </button>
        </div>
      </div>

      <ol className="execution-phase-rail" aria-label="Execution phases">
        {presentation.phases.map((phase) => {
          const complete = terminalStatuses.has(phase.status);
          const current = phase.status === "running" || phase.status === "repairing";
          return (
            <li
              key={phase.id}
              className={current ? "is-current" : complete ? "is-complete" : ""}
              aria-current={current ? "step" : undefined}
            >
              <span>{phase.order}</span>
              {phase.label}
            </li>
          );
        })}
      </ol>

      {showLimitations && visiblePhases.length === 0 ? (
        <div className="execution-limitations-empty" role="status">
          <CheckIcon />
          <span><strong>No active limitations</strong><small>The signed plan has no degraded, failed, withheld, repairing, cancelled, or unavailable phase.</small></span>
        </div>
      ) : (
        <div className="execution-phase-groups">
          {visiblePhases.map((phase) => (
            <ExecutionPhaseGroup
              key={phase.id}
              phase={phase}
              allSteps={presentation.phases.flatMap((candidate) => candidate.steps)}
              toolActivities={phase.id === "tools" ? toolActivities : []}
              expanded={expanded}
              running={running}
              onPhaseToggle={togglePhase}
              onStepToggle={toggleStep}
              onCheckToggle={toggleCheck}
              onProof={onProof}
              onCalculations={onCalculations}
              onLineage={onLineage}
            />
          ))}
        </div>
      )}

      {showLimitations && presentation.limitations.length > 0 && (
        <aside className="execution-limitations" aria-label="Execution limitations">
          <span className="eyebrow">Bounded limitations</span>
          <ul>{presentation.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
        </aside>
      )}

      <footer className="execution-plan-footer">
        <span><ShieldIcon /> Execution transparency exposes governed facts, never private chain-of-thought or model reasoning.</span>
        <span className="execution-plan-identities" aria-label="Workspace run identity">
          <code title={presentation.runID}>run {shortID(presentation.runID)}</code>
          {traceID && <code title={traceID}>trace {shortID(traceID)}</code>}
          <code title={presentation.projectionSHA256}>projection {shortID(presentation.projectionSHA256)}</code>
          <code title={presentation.presentationSHA256}>view {shortID(presentation.presentationSHA256)}</code>
        </span>
      </footer>
    </section>
  );
}

function ExecutionPhaseGroup({
  phase,
  allSteps,
  toolActivities,
  expanded,
  running,
  onPhaseToggle,
  onStepToggle,
  onCheckToggle,
  onProof,
  onCalculations,
  onLineage
}: {
  phase: PhasePresentation;
  allSteps: StepPresentation[];
  toolActivities: ToolActivity[];
  expanded: ExpansionState;
  running: boolean;
  onPhaseToggle: (id: string, open: boolean) => void;
  onStepToggle: (id: string, open: boolean) => void;
  onCheckToggle: (id: string, open: boolean) => void;
  onProof: (refs: string[]) => void;
  onCalculations: (refs: string[]) => void;
  onLineage: () => void;
}) {
  const linkedTerminal = toolActivities.filter((activity) => terminalStatuses.has(activity.item.status)).length;
  const terminal = phase.terminalSteps + linkedTerminal;
  const total = phase.totalSteps + toolActivities.length;
  const open = expanded.phases.has(phase.id);

  return (
    <details
      className={`execution-phase-group status-${phase.status}`}
      aria-label={`${humanize(phase.id)} phase`}
      open={open}
      onToggle={(event) => onPhaseToggle(phase.id, event.currentTarget.open)}
    >
      <summary onKeyDown={(event) => keyboardToggle(event, open, (next) => onPhaseToggle(phase.id, next))}>
        <span>
          <small>Phase {phase.order} · {phase.requirementLabel}</small>
          <strong>{phase.label}</strong>
        </span>
        <em>{terminal} / {total} closed</em>
        <span className={`execution-status status-${phase.status}`}>{phase.statusLabel}</span>
      </summary>
      <div className="execution-phase-objective">
        <span className="execution-depth">Details</span>
        <p>{phase.objective}</p>
        <small>{phase.summary}</small>
      </div>

      {phase.waves.map((wave) => (
        <section className="execution-wave" key={wave.id} aria-label={wave.label}>
          {wave.wave && (
            <header>
              <span><SparkIcon /><strong>{wave.label}</strong></span>
              <em>{wave.steps.length} {wave.parallel ? "parallel specialists" : "specialist"}</em>
            </header>
          )}
          <ol
            className="execution-step-list"
            aria-label={`${phase.label} execution stages`}
            start={allSteps.indexOf(wave.steps[0]) + 1}
          >
            {wave.steps.map((step) => (
              <ExecutionStepCard
                key={step.id}
                step={step}
                index={allSteps.indexOf(step)}
                expanded={expanded}
                running={running}
                onStepToggle={onStepToggle}
                onCheckToggle={onCheckToggle}
                onProof={onProof}
                onCalculations={onCalculations}
                onLineage={onLineage}
              />
            ))}
          </ol>
        </section>
      ))}

      {toolActivities.length > 0 && (
        <section className="execution-linked-tools" aria-label="Deterministic tool activities">
          <header>
            <span><ChipIcon /><strong>Deterministic operations</strong></span>
            <em>{toolActivities.length} receipt-backed checks</em>
          </header>
          <div className="execution-checklist">
            {toolActivities.map((activity) => (
              <ChecklistRow
                key={`${activity.sourceStepID}:${activity.item.id}`}
                item={activity.item}
                itemKey={checkKey(activity.sourceStepID, activity.item.id)}
                sourceLabel={activity.sourceStepLabel}
                expanded={expanded.checks.has(checkKey(activity.sourceStepID, activity.item.id))}
                onToggle={onCheckToggle}
                onProof={onProof}
                onCalculations={onCalculations}
              />
            ))}
          </div>
        </section>
      )}

      {phase.steps.length === 0 && toolActivities.length === 0 && (
        <p className="execution-phase-empty">
          {running && phase.mandatory
            ? "Waiting for an accepted dependency."
            : "No standalone activity was required for this phase."}
        </p>
      )}
    </details>
  );
}

function ExecutionStepCard({
  step,
  index,
  expanded,
  running,
  onStepToggle,
  onCheckToggle,
  onProof,
  onCalculations,
  onLineage
}: {
  step: StepPresentation;
  index: number;
  expanded: ExpansionState;
  running: boolean;
  onStepToggle: (id: string, open: boolean) => void;
  onCheckToggle: (id: string, open: boolean) => void;
  onProof: (refs: string[]) => void;
  onCalculations: (refs: string[]) => void;
  onLineage: () => void;
}) {
  const open = expanded.steps.has(step.id);
  const checklist = step.phaseID === "tools"
    ? step.checklist
    : step.checklist.filter((item) =>
      !item.references.some((reference) => reference.kind === "calculation"));
  const proofReferences = unique(step.references
    .filter((reference) => reference.kind === "evidence")
    .map((reference) => reference.id));

  return (
    <li className="execution-step-list-item">
      <details
        className={`execution-step status-${step.status}`}
        aria-label={`${step.label} step`}
        open={open}
        onToggle={(event) => onStepToggle(step.id, event.currentTarget.open)}
      >
        <summary onKeyDown={(event) => keyboardToggle(event, open, (next) => onStepToggle(step.id, next))}>
          <span className="execution-step-index">{String(index + 1).padStart(2, "0")}</span>
          <span className="execution-step-icon"><StatusIcon status={step.status} /></span>
          <span className="execution-step-title">
            <small>{humanize(step.kind)}{step.wave ? ` · wave ${step.wave}` : ""} · {step.requirementLabel}</small>
            <strong>{step.label}</strong>
            <em>{step.summary}</em>
          </span>
          <span className={`execution-status status-${step.status}`}>{step.statusLabel}</span>
        </summary>

        <div className="execution-step-detail">
          <div className="execution-objective">
            <span className="execution-depth">Details</span>
            <p>{step.objective}</p>
          </div>
          <dl className="execution-metadata">
            <div><dt>Authority</dt><dd>{step.authorityLabel}</dd></div>
            <div><dt>Route</dt><dd className="execution-route-value"><span className="execution-route-badge">{step.routeLabel}</span></dd></div>
            <div><dt>Depends on</dt><dd className="execution-dependency-value">{step.dependencies.length ? step.dependencies.map(humanize).join(", ") : "No unresolved dependency"}</dd></div>
            <div><dt>Attempt</dt><dd>{step.attempt} / {step.maxAttempts}</dd></div>
            <div><dt>Duration</dt><dd>{formatDuration(step.durationMS)}</dd></div>
            <div><dt>Contract</dt><dd>{step.requirementLabel}</dd></div>
            {step.capabilities.length > 0 && (
              <div><dt>Capabilities</dt><dd className="execution-dependency-value">{step.capabilities.map(humanize).join(", ")}</dd></div>
            )}
            {step.evidenceRequirements.length > 0 && (
              <div><dt>Evidence</dt><dd className="execution-dependency-value">{step.evidenceRequirements.map(humanize).join(", ")}</dd></div>
            )}
            {(step.failureCode || step.degradationCode) && (
              <div><dt>Outcome code</dt><dd>{humanize(step.failureCode ?? step.degradationCode ?? "")}</dd></div>
            )}
          </dl>

          {checklist.length > 0 && (
            <div className="execution-checklist" aria-label={`${step.label} checklist`}>
              {checklist.map((item) => (
                <ChecklistRow
                  key={item.id}
                  item={item}
                  itemKey={checkKey(step.id, item.id)}
                  expanded={expanded.checks.has(checkKey(step.id, item.id))}
                  onToggle={onCheckToggle}
                  onProof={onProof}
                  onCalculations={onCalculations}
                />
              ))}
            </div>
          )}

          <div className="execution-step-actions">
            {proofReferences.length > 0 && <button onClick={() => onProof(proofReferences)}>Open evidence</button>}
            <button onClick={onLineage}>Inspect lineage</button>
            <code title={step.id}>step {shortID(step.id)}</code>
          </div>
        </div>
      </details>
    </li>
  );
}

function ChecklistRow({
  item,
  itemKey,
  sourceLabel,
  expanded,
  onToggle,
  onProof,
  onCalculations
}: {
  item: ChecklistPresentation;
  itemKey: string;
  sourceLabel?: string;
  expanded: boolean;
  onToggle: (id: string, open: boolean) => void;
  onProof: (refs: string[]) => void;
  onCalculations: (refs: string[]) => void;
}) {
  const evidence = item.references.filter((reference) => reference.kind === "evidence").map((reference) => reference.id);
  const calculations = item.references.filter((reference) => reference.kind === "calculation").map((reference) => reference.id);
  return (
    <details
      className={`execution-check status-${item.status}`}
      open={expanded}
      onToggle={(event) => onToggle(itemKey, event.currentTarget.open)}
    >
      <summary onKeyDown={(event) => keyboardToggle(event, expanded, (next) => onToggle(itemKey, next))}>
        <StatusIcon status={item.status} />
        <span>
          <strong>{item.label}</strong>
          <small>{item.statusLabel}</small>
        </span>
        <em>{item.authorityLabel} · {item.requirementLabel}</em>
      </summary>
      <div className="execution-check-proof">
        <span className="execution-depth">Proof</span>
        <p>{item.safeDetail}</p>
        {sourceLabel && <small>Emitted by {sourceLabel}.</small>}
        <dl>
          <div><dt>Authority</dt><dd>{item.authorityLabel}</dd></div>
          <div><dt>Check ID</dt><dd><code>{item.id}</code></dd></div>
          <div><dt>Completed</dt><dd>{formatTimestamp(item.completedAt)}</dd></div>
        </dl>
        <div className="execution-check-actions">
          {evidence.length > 0 && <button type="button" onClick={() => onProof(evidence)}>Open evidence</button>}
          {calculations.length > 0 && (
            <button type="button" onClick={() => onCalculations(calculations)}>Open calculation</button>
          )}
          {item.references.length > 0 && <code>{item.references.map((reference) => reference.id).join(" · ")}</code>}
        </div>
      </div>
    </details>
  );
}

function collectToolActivities(presentation: ExecutionPresentation): ToolActivity[] {
  return presentation.phases
    .filter((phase) => phase.id !== "tools")
    .flatMap((phase) => phase.steps.flatMap((step) =>
      step.checklist
        .filter((item) =>
          item.id.startsWith("tool-") &&
          item.references.some((reference) => reference.kind === "calculation"))
        .map((item) => ({
          sourceStepID: step.id,
          sourceStepLabel: step.label,
          item
        }))
    ));
}

function defaultExpansion(presentation: ExecutionPresentation): ExpansionState {
  return mergeActiveExpansion(emptyExpansion(), presentation);
}

function mergeActiveExpansion(
  current: ExpansionState,
  presentation: ExecutionPresentation
): ExpansionState {
  const phases = new Set(current.phases);
  const steps = new Set(current.steps);
  const checks = new Set(current.checks);
  for (const phase of presentation.phases) {
    if (phase.status === "running" || phase.status === "repairing" || phase.attention) {
      phases.add(phase.id);
    }
    for (const step of phase.steps) {
      if (step.status === "running" || step.status === "repairing" || step.attention) {
        phases.add(phase.id);
        steps.add(step.id);
      }
      for (const item of step.checklist) {
        if (item.status === "running" || item.status === "repairing" || item.attention) {
          checks.add(checkKey(step.id, item.id));
        }
      }
    }
  }
  return { phases, steps, checks };
}

function emptyExpansion(): ExpansionState {
  return { phases: new Set(), steps: new Set(), checks: new Set() };
}

function toggleID(values: Set<string>, id: string, open: boolean): Set<string> {
  const next = new Set(values);
  if (open) next.add(id);
  else next.delete(id);
  return next;
}

function keyboardToggle(
  event: KeyboardEvent<HTMLElement>,
  open: boolean,
  toggle: (open: boolean) => void
) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  toggle(!open);
}

function checkKey(stepID: string, checkID: string): string {
  return `${stepID}:${checkID}`;
}

function StatusIcon({ status }: { status: ExecutionStatus }) {
  if (status === "passed") return <CheckIcon />;
  if (status === "failed" || status === "withheld" || status === "cancelled") return <ShieldIcon />;
  if (status === "running" || status === "repairing") return <SparkIcon />;
  return <ChipIcon />;
}

function shortID(value: string): string {
  return value.length > 12 ? value.slice(0, 12) : value;
}

function formatDuration(duration = 0): string {
  if (duration <= 0) return "Not recorded";
  if (duration < 1000) return `${duration} ms`;
  return `${(duration / 1000).toFixed(duration >= 10000 ? 0 : 1)} s`;
}

function formatTimestamp(value?: string): string {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString("en-US", { timeZone: "UTC" }) + " UTC";
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}
