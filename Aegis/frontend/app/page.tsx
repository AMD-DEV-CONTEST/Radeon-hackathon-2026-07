"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Incident } from "@/lib/api";
import { SeverityChip } from "@/components/SeverityChip";
import { StatusBadge } from "@/components/StatusBadge";

function timeAgo(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function IncidentListPage() {
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await api.listIncidents();
        if (!cancelled) setIncidents(data);
      } catch (e) {
        if (!cancelled) setError("Couldn't reach the Aegis backend. Is it running?");
      }
    }
    load();
    const interval = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="main">
      <div className="stream">
        <div className="stream-header">Incident stream</div>
        {error && <div className="empty-state">{error}</div>}
        {incidents && incidents.length === 0 && (
          <div className="empty-state">
            No incidents yet.
            <br />
            POST to /api/v1/incidents to trigger an investigation.
          </div>
        )}
        {incidents?.map((incident) => (
          <Link key={incident.id} href={`/incidents/${incident.id}`} className="incident-row">
            <div className="incident-row-top">
              <SeverityChip severity={incident.severity} />
              <StatusBadge status={incident.status} />
            </div>
            <div className="incident-title">{incident.title}</div>
            <div className="incident-meta">
              {incident.source} · {timeAgo(incident.created_at)}
            </div>
          </Link>
        ))}
      </div>
      <div className="detail-empty">
        Select an incident from the stream to view its investigation trace, evidence,
        and root-cause analysis.
      </div>
    </div>
  );
}
