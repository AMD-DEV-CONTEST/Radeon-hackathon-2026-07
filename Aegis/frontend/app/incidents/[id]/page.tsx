"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, IncidentDetail } from "@/lib/api";
import { SeverityChip } from "@/components/SeverityChip";
import { StatusBadge } from "@/components/StatusBadge";

export default function IncidentDetailPage() {
  const params = useParams<{ id: string }>();
  const [incident, setIncident] = useState<IncidentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await api.getIncident(params.id);
        if (!cancelled) setIncident(data);
      } catch {
        if (!cancelled) setError("Couldn't load this incident.");
      }
    }
    load();
    const interval = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [params.id]);

  async function handleApproval(approved: boolean) {
    setApproving(true);
    try {
      const token = localStorage.getItem("aegis_token");
      await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL}/incidents/${params.id}/remediation/approve`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ approved }),
        }
      );
      const refreshed = await api.getIncident(params.id);
      setIncident(refreshed);
    } finally {
      setApproving(false);
    }
  }

  if (error) return <div className="detail-empty">{error}</div>;
  if (!incident) return <div className="detail-empty">Loading incident…</div>;

  return (
    <div className="detail">
      <div className="detail-header">
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
          <SeverityChip severity={incident.severity} />
          <StatusBadge status={incident.status} />
        </div>
        <h1>{incident.title}</h1>
        <p style={{ color: "var(--text-secondary)", fontSize: 14, maxWidth: 720 }}>
          {incident.description}
        </p>
      </div>

      {incident.root_cause_summary && (
        <div className="root-cause-card">
          <div className="root-cause-label">Root cause</div>
          <div style={{ fontSize: 15, color: "var(--text-primary)" }}>
            {incident.root_cause_summary}
          </div>
          {incident.root_cause_confidence !== null && (
            <>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-tertiary)", marginTop: 12 }}>
                Confidence: {Math.round(incident.root_cause_confidence * 100)}%
              </div>
              <div className="confidence-bar-track">
                <div
                  className="confidence-bar-fill"
                  style={{ width: `${incident.root_cause_confidence * 100}%` }}
                />
              </div>
            </>
          )}

          {incident.status === "remediation_pending_approval" && (
            <div className="btn-row">
              <button className="btn btn-primary" disabled={approving} onClick={() => handleApproval(true)}>
                Approve remediation
              </button>
              <button className="btn" disabled={approving} onClick={() => handleApproval(false)}>
                Reject
              </button>
            </div>
          )}
        </div>
      )}

      <div className="trace">
        <div className="trace-header">Agent investigation trace</div>
        {incident.agent_steps?.length ? (
          <div className="trace-line">
            {incident.agent_steps.map((step) => (
              <div className="trace-node" key={step.id}>
                <div className="trace-node-header">
                  <span className="trace-agent-name">{step.agent_name}</span>
                  <span className="trace-meta">
                    {step.duration_ms.toFixed(0)}ms
                    {step.tokens_per_second ? ` · ${step.tokens_per_second.toFixed(1)} tok/s` : ""}
                    {step.confidence !== null ? ` · confidence ${Math.round(step.confidence * 100)}%` : ""}
                  </span>
                </div>
                <div className="trace-summary">{step.output_summary}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">Investigation hasn't started producing steps yet.</div>
        )}
      </div>

      <div className="evidence-grid">
        <div className="trace-header" style={{ marginTop: 8 }}>
          Evidence
        </div>
        {incident.evidence.length === 0 && (
          <div className="empty-state">No evidence collected yet.</div>
        )}
        {incident.evidence.map((e) => (
          <div className="evidence-card" key={e.id}>
            <div className="evidence-type">
              {e.evidence_type} · {e.source_agent}
            </div>
            <div className="evidence-summary">{e.summary}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
