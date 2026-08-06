import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { AnalyticsData } from '../types';
import { StatCard } from '../components/StatCard';
import { BarChart } from '../components/BarChart';

export const Analytics: React.FC = () => {
  const [data, setData] = useState<AnalyticsData | null>(null);

  useEffect(() => {
    api.getAnalytics().then(setData).catch(console.error);
  }, []);

  if (!data) return <div className="page-container"><div className="spinner"></div></div>;

  const maxFailure = Math.max(...(data.topFailureModes || []).map(d => d.value), 1);
  const maxAction = Math.max(...(data.topActions || []).map(d => d.value), 1);

  return (
    <div className="page-container animate-fade-in">
      <div className="hero-section">
        <h1 className="hero-title text-gradient">Global Analytics</h1>
        <p className="hero-subtitle">Insights aggregated across all parsed documents and assets.</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '2rem' }}>
        <StatCard title="Total Knowledge Chunks" value={data.totalChunks} icon="▤" variant="blue" />
        <StatCard title="Total Assets Tracked" value={data.totalAssets} icon="◎" variant="teal" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem', marginBottom: '2rem' }}>
        <div className="card">
          <h2 style={{ fontSize: '1.25rem', marginBottom: '1rem' }}>Top Failure Modes</h2>
          <BarChart data={data.topFailureModes || []} max={maxFailure} />
        </div>
        <div className="card">
          <h2 style={{ fontSize: '1.25rem', marginBottom: '1rem' }}>Top Maintenance Actions</h2>
          <BarChart data={data.topActions || []} max={maxAction} />
        </div>
      </div>

      <div className="card">
        <h2 style={{ fontSize: '1.25rem', marginBottom: '1rem' }}>High-Risk Assets</h2>
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>Asset Tag</th>
                <th>Risk Score</th>
                <th>Last Failure Date</th>
              </tr>
            </thead>
            <tbody>
              {(data.assetsRankedByRisk || []).map((asset, i) => (
                <tr key={asset.tag}>
                  <td style={{ fontWeight: 600, color: 'var(--accent-primary)' }}>{asset.tag}</td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <div style={{ width: '100px', height: '6px', background: 'var(--bg-tertiary)', borderRadius: '3px', overflow: 'hidden' }}>
                        <div style={{ width: `${asset.riskScore}%`, height: '100%', background: asset.riskScore > 75 ? 'var(--accent-danger)' : asset.riskScore > 50 ? 'var(--accent-warning)' : 'var(--accent-primary)' }}></div>
                      </div>
                      <span style={{ fontSize: '0.85rem' }}>{asset.riskScore}/100</span>
                    </div>
                  </td>
                  <td>{new Date(asset.lastFailure || Date.now()).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
