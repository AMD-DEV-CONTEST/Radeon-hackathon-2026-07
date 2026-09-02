import { useDeferredValue, useState } from "react";
import type { FinancialCompany, FinancialResult, FinancialSummary, PeerEvaluationSuite, ProductCatalog, ProductCompany, ScenarioControl } from "../types";
import { ArrowIcon, ShieldIcon } from "./Icons";

type Mode = "standalone" | "comparison";

type Props = {
  catalog: ProductCatalog;
  financials: FinancialSummary;
  peers: PeerEvaluationSuite;
  scenario: ScenarioControl;
  live: boolean;
  onQuestion: (value: string) => void;
};

export function ResearchScope({ catalog, financials, peers, scenario, live, onQuestion }: Props) {
  const [mode, setMode] = useState<Mode>("standalone");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const deferredQuery = useDeferredValue(query.trim().toLowerCase());
  const companyByID = new Map(catalog.companies.map((company) => [company.company_id, company]));
  const financialByID = new Map(financials.companies.map((company) => [company.company_id, company]));
  const selectedLane = selected.length === 2
    ? catalog.peer_lanes.find((lane) => selected.every((id) => lane.company_ids.includes(id)))
    : undefined;
  const selectedEvaluation = selectedLane
    ? peers.lanes.find((lane) => lane.lane_id === selectedLane.lane_id)
    : undefined;
  const visible = catalog.companies.filter((company) => {
    if (!deferredQuery) return true;
    return [company.display_name, company.primary_ticker, company.research_cluster, company.peer_group]
      .some((value) => value.toLowerCase().includes(deferredQuery));
  });

  function changeMode(next: Mode) {
    setMode(next);
    setSelected([]);
  }

  function choose(company: ProductCompany) {
    const next = mode === "standalone"
      ? [company.company_id]
      : selected.includes(company.company_id)
        ? selected.filter((id) => id !== company.company_id)
        : [...selected, company.company_id].slice(-2);
    setSelected(next);
    const companies = next.map((id) => companyByID.get(id)).filter((item): item is ProductCompany => Boolean(item));
    if (live && company.research_enabled && mode === "standalone" && companies.length === 1) {
      onQuestion(`Research ${companies[0].display_name} as a long-term business. Explain its business model, financial quality, risks, valuation assumptions, and thesis invalidation conditions.`);
    }
    const lane = peers.lanes.find((item) => next.every((id) => item.company_ids.includes(id)));
    if (live && lane?.promoted && mode === "comparison" && companies.length === 2) {
      onQuestion(`Compare ${companies[0].display_name} and ${companies[1].display_name} as long-term businesses. Show only metrics with approved comparability receipts and explain every caveat.`);
    }
  }

  return (
    <section className="research-scope" aria-labelledby="research-scope-title">
      <header>
        <div>
          <span className="eyebrow">Governed product universe</span>
          <h2 id="research-scope-title">Twenty companies. No implied comparability.</h2>
        </div>
        <span className="catalog-count">{catalog.companies.length} issuers · {catalog.peer_lanes.length} candidate peer lanes</span>
      </header>
      <div className="scope-mode" aria-label="Research mode">
        <button type="button" aria-pressed={mode === "standalone"} onClick={() => changeMode("standalone")}>Research one company</button>
        <button type="button" aria-pressed={mode === "comparison"} onClick={() => changeMode("comparison")}>Compare companies</button>
      </div>
      <label className="company-search">
        <span className="sr-only">Search company, ticker, or cluster</span>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search company, ticker, cluster, or peer group" />
      </label>
      <div className="company-grid" role="list" aria-label="Technology 20 companies">
        {visible.map((company) => {
          const available = live && company.research_enabled;
          const isSelected = selected.includes(company.company_id);
          return (
            <button
              type="button"
              role="listitem"
              key={company.company_id}
              className={isSelected ? "is-selected" : ""}
              aria-pressed={isSelected}
              onClick={() => choose(company)}
              title={available ? `Research ${company.display_name}` : `Inspect bounded evidence for ${company.display_name}`}
            >
              <span><strong>{company.primary_ticker}</strong><small>{company.display_name}</small></span>
              <span className={`activation-state state-${company.activation_state}`}>{company.activation_state.replaceAll("_", " ")}</span>
            </button>
          );
        })}
      </div>
      {visible.length === 0 && <p className="catalog-empty">No governed company matches this search.</p>}
      {mode === "standalone" && selected.length === 1 && financialByID.get(selected[0]) && (
        <CompanyAuthority
          company={financialByID.get(selected[0])!}
          profile={companyByID.get(selected[0])!}
          scenario={scenario}
        />
      )}
      {mode === "comparison" && (
        <div className="peer-lanes">
          <span className="eyebrow">Candidate peer lanes</span>
          {catalog.peer_lanes.map((lane) => {
            const evaluation = peers.lanes.find((item) => item.lane_id === lane.lane_id);
            return (
            <button type="button" key={lane.lane_id} disabled={!lane.enabled}>
              <span>{lane.company_ids.map((id) => companyByID.get(id)?.primary_ticker ?? id).join(" / ")}</span>
              <small>{evaluation?.releasable_metric_ids.length ?? 0} metric receipts · {evaluation?.withheld_metric_ids.length ?? 0} withheld</small>
              <ArrowIcon />
            </button>
          )})}
        </div>
      )}
      {mode === "comparison" && selected.length === 2 && (
        <div className={`comparison-decision ${selectedLane?.enabled ? "is-enabled" : "is-guarded"}`} role="status">
          <ShieldIcon />
          {selectedLane ? (
            <div>
              <span className="eyebrow">{selectedLane.enabled ? "Comparison authorized" : "Comparison remains guarded"}</span>
              <strong>{selectedLane.decision_question}</strong>
              <p>
                {selectedEvaluation?.releasable_metric_ids.length ?? 0} metric receipts are releasable;{" "}
                {selectedEvaluation?.withheld_metric_ids.length ?? selectedLane.allowed_metric_ids.length} are withheld.
              </p>
              {selectedEvaluation && (
                <div className="comparison-metrics" role="region" aria-label="Metric-level comparison authority">
                  {selectedEvaluation.receipts.map((receipt) => (
                    <article key={receipt.receipt_sha256}>
                      <span>{labelOperation(receipt.operands[0]?.canonical_metric_id ?? "unknown metric")}</span>
                      <strong>{labelReason(receipt.disposition)}</strong>
                      {receipt.required_caveat_ids?.length
                        ? <small>{receipt.required_caveat_ids.map(labelReason).join(" · ")}</small>
                        : <small>No additional metric caveat recorded.</small>}
                    </article>
                  ))}
                  {selectedEvaluation.withheld_metric_ids.map((metricID) => (
                    <article className="is-withheld" key={metricID}>
                      <span>{labelOperation(metricID)}</span>
                      <strong>Withheld</strong>
                      <small>No approved comparison receipt.</small>
                    </article>
                  ))}
                </div>
              )}
              <small>{selectedLane.reason_codes.map(labelReason).join(" · ")}</small>
            </div>
          ) : (
            <div>
              <span className="eyebrow">No governed peer lane</span>
              <strong>This pair is available for standalone research only.</strong>
              <p>SignalForge will not infer comparability from cluster membership.</p>
            </div>
          )}
        </div>
      )}
      <p className="catalog-boundary"><ShieldIcon /><span><strong>{live ? "Activation is enforced at runtime." : "Catalog preview in fixture mode."}</strong>{catalog.claim_boundary}</span></p>
    </section>
  );
}

function CompanyAuthority({
  company,
  profile,
  scenario
}: {
  company: FinancialCompany;
  profile: ProductCompany;
  scenario: ScenarioControl;
}) {
  const evidenceRecency = latestValue(company.results.map((result) => result.source_as_of));
  const latestPeriod = latestValue(company.results.flatMap((result) => result.periods));
  return (
    <div className="company-authority">
      <div className="company-authority-heading">
        <span className="eyebrow">Deterministic authority · {company.primary_ticker}</span>
        <strong>{company.display_name}</strong>
        <small>{labelReason(profile.research_cluster)} · {labelReason(profile.peer_group)}</small>
      </div>
      <dl className="company-authority-facts">
        <div><dt>Activation</dt><dd>{labelReason(profile.activation_state)}</dd></div>
        <div><dt>Evidence recency</dt><dd>{evidenceRecency ? formatDate(evidenceRecency) : "Unavailable"}</dd></div>
        <div><dt>Latest governed period</dt><dd>{latestPeriod ?? "Unavailable"}</dd></div>
        <div><dt>Price observation date</dt><dd>Unavailable · not activated</dd></div>
        <div><dt>Scenario assumptions</dt><dd>{labelScenario(scenario)}</dd></div>
        <div><dt>Authority</dt><dd>{company.results.length} receipts · {company.abstentions.length} abstentions</dd></div>
      </dl>
      <div className="company-authority-boundary">
        <span className="eyebrow">Current boundary</span>
        <strong>{profile.research_enabled ? "Research enabled" : "Evidence inspection only"}</strong>
        <small>{profile.reason_codes.map(labelReason).join(" · ")}</small>
      </div>
      <div className="authority-results">
        {company.results.slice(0, 7).map((result) => (
          <article key={result.operation_id}>
            <span>{labelOperation(result.operation_id)}</span>
            <strong>{renderOutput(result)}</strong>
            <small>{result.periods.at(-1)} · receipt {result.receipt_sha256.slice(0, 8)}</small>
          </article>
        ))}
      </div>
      {company.abstentions.length > 0 && (
        <div className="authority-abstentions" role="region" aria-label="Explicit missing evidence">
          <span className="eyebrow">Explicitly withheld</span>
          {company.abstentions.slice(0, 4).map((item) => (
            <article key={`${item.operation_id}-${item.code}`}>
              <strong>{labelOperation(item.operation_id)}</strong>
              <small>{labelReason(item.code)}</small>
            </article>
          ))}
        </div>
      )}
      <p>{company.results.length === 0 ? "No deterministic result passed authority." : "Every value shown is formula-derived and hash-bound to SEC evidence."}</p>
    </div>
  );
}

function labelOperation(value: string) {
  return value.split(".").at(-1)?.replaceAll("_", " ") ?? value;
}

function labelReason(value: string) {
  const words = value.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function renderOutput(result: FinancialResult) {
  const output = result.outputs[0]?.quantity;
  if (!output) return "Unavailable";
  const numeric = Number(output.value);
  if (!Number.isFinite(numeric)) return output.value;
  if (output.unit === "ratio") return `${(numeric * 100).toFixed(1)}%`;
  if (output.unit === "currency") {
    return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1, style: "currency", currency: output.currency ?? "USD" }).format(numeric);
  }
  return output.value;
}

function latestValue(values: string[]) {
  return values.filter(Boolean).sort().at(-1);
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone: "UTC" }).format(date);
}

function labelScenario(scenario: ScenarioControl) {
  return `${labelReason(scenario.rates)} · AI spending ${labelReason(scenario.ai_spending).toLowerCase()}`;
}
