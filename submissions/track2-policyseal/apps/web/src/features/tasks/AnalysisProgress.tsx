import { Check, Circle, CircleAlert, LoaderCircle } from "lucide-react";

import { Badge } from "../../components/ui/Badge";
import type { Revision, StageEvent } from "../../lib/types";
import { statusTone, titleCase } from "../../lib/utils";

const STAGES = [
  ["preflight", "Capability preflight"],
  ["parse", "Document parsing"],
  ["deterministic_scan", "Deterministic scan"],
  ["semantic_classification", "Semantic classification"],
  ["policy_evaluation", "Policy execution"],
  ["output_validation", "Output validation"],
  ["residual_check", "Residual safety check"],
] as const;

interface AnalysisProgressProps {
  revision: Revision;
  events: StageEvent[];
  running: boolean;
  error?: string;
}

function eventStatus(stage: string, events: StageEvent[], revision: Revision, running: boolean) {
  const matching = events.filter((event) => event.stage === stage).at(-1);
  if (matching) {
    if (["completed", "validated", "passed", "pass", "exportable"].includes(matching.status)) {
      return "complete";
    }
    if (["block", "blocked", "processing_failed"].includes(matching.status)) return "failed";
    return "active";
  }

  const stageNames = events.map((event) => event.stage);
  if (stage === "deterministic_scan" && stageNames.includes("semantic_classification")) {
    return "complete";
  }
  if (stage === "output_validation" && stageNames.includes("render")) {
    return revision.output_sha256 ? "complete" : "active";
  }
  if (stage === "residual_check" && !running && revision.status !== "draft") {
    return revision.status === "processing_failed" ? "failed" : "complete";
  }
  return "pending";
}

export function AnalysisProgress({ revision, events, running, error }: AnalysisProgressProps) {
  return (
    <section className="analysis-progress" aria-labelledby="analysis-progress-title">
      <div className="panel-heading panel-heading--bordered">
        <div>
          <p className="section-label">Revision {revision.revision_number}</p>
          <h2 id="analysis-progress-title">Local analysis</h2>
        </div>
        <Badge tone={statusTone(revision.status)}>
          {running ? "Analyzing" : titleCase(revision.status)}
        </Badge>
      </div>

      <ol className="stage-list">
        {STAGES.map(([stage, label]) => {
          const state = eventStatus(stage, events, revision, running);
          const Icon =
            state === "complete"
              ? Check
              : state === "failed"
                ? CircleAlert
                : state === "active"
                  ? LoaderCircle
                  : Circle;
          return (
            <li className={`stage-row stage-row--${state}`} key={stage}>
              <Icon className={state === "active" ? "spin" : undefined} size={16} aria-hidden="true" />
              <span>{label}</span>
              <small>{state === "complete" ? "Complete" : state === "failed" ? "Attention" : state === "active" ? "Running" : "Pending"}</small>
            </li>
          );
        })}
      </ol>

      {error ? <p className="analysis-error" role="alert">{error}</p> : null}
      {!running && !error ? (
        <div className="analysis-conclusion">
          <strong>{titleCase(revision.status)}</strong>
          <span>{Object.values(revision.action_counts).reduce((sum, count) => sum + (count ?? 0), 0)} policy decisions recorded</span>
        </div>
      ) : null}
    </section>
  );
}
