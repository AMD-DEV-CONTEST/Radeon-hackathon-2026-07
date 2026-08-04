import { ArrowRight, BookOpenText, FileSearch } from "lucide-react";

import { Badge } from "../../components/ui/Badge";
import type { Decision, EvidenceRecord, ReviewRegion } from "../../lib/types";
import { actionTone, titleCase } from "../../lib/utils";

interface DecisionInspectorProps {
  decision?: Decision;
  region?: ReviewRegion;
  evidence: EvidenceRecord[];
  contextLabel: string;
}

function targetPreview(decision: Decision, region: ReviewRegion): string {
  if (decision.action === "keep" || decision.action === "require_approval") {
    return region.source_text;
  }
  if (["remove", "block"].includes(decision.action)) {
    return "Not disclosed";
  }
  if (decision.action === region.action && decision.transform === region.transform) {
    return region.output_preview ?? "Not disclosed";
  }
  return decision.transform ? titleCase(decision.transform) : titleCase(decision.action);
}

export function DecisionInspector({
  decision,
  region,
  evidence,
  contextLabel,
}: DecisionInspectorProps) {
  if (!decision || !region) {
    return (
      <section className="decision-inspector decision-inspector--empty">
        <FileSearch size={20} aria-hidden="true" />
        <span>Select a matrix cell or document region.</span>
      </section>
    );
  }

  const citedEvidence = evidence.filter((item) => decision.evidence_ids.includes(item.id));

  return (
    <section className="decision-inspector" aria-labelledby="decision-inspector-title">
      <div className="inspector-heading">
        <div>
          <p className="section-label">Selected decision / {contextLabel}</p>
          <h3 id="decision-inspector-title">{region.location}</h3>
        </div>
        <Badge tone={actionTone(decision.action)}>{titleCase(decision.action)}</Badge>
      </div>

      <div className="inspector-grid">
        <section className="diff-panel">
          <div className="diff-panel__heading">
            <span>Source</span>
            <Badge>{titleCase(region.category)}</Badge>
          </div>
          <p>{region.source_text}</p>
        </section>

        <div className="diff-arrow" aria-hidden="true">
          <ArrowRight size={17} />
        </div>

        <section className="diff-panel diff-panel--target">
          <div className="diff-panel__heading">
            <span>Minimum disclosure</span>
            {decision.transform ? <Badge tone="info">{titleCase(decision.transform)}</Badge> : null}
          </div>
          <p>{targetPreview(decision, region)}</p>
        </section>

        <section className="evidence-panel">
          <div className="evidence-panel__heading">
            <BookOpenText size={15} aria-hidden="true" />
            <span>Rule and evidence</span>
          </div>
          <p className="decision-reason">{decision.reason}</p>
          <div className="citation-list">
            {decision.rule_ids.map((ruleId) => (
              <Badge key={ruleId} tone="info">{ruleId}</Badge>
            ))}
            {decision.evidence_ids.map((evidenceId) => (
              <Badge key={evidenceId}>{evidenceId}</Badge>
            ))}
          </div>
          {citedEvidence.map((item) => (
            <details key={item.id}>
              <summary>{item.id} / {item.title}</summary>
              <p>{item.excerpt}</p>
            </details>
          ))}
        </section>
      </div>
    </section>
  );
}
