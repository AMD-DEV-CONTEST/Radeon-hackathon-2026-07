import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { DashboardData } from '../types';
import { StatCard } from '../components/StatCard';

export const Dashboard: React.FC = () => {
  const [data, setData] = useState<DashboardData | null>(null);

  useEffect(() => {
    api.getDashboard().then(setData).catch(console.error);
  }, []);

  if (!data) return <div className="page-container"><div className="spinner"></div></div>;

  return (
    <div className="page-container animate-fade-in">
      <div className="hero-section">
        <h1 className="hero-title text-gradient">Industrial Intelligence, Redefined.</h1>
        <p className="hero-subtitle">System Status: {data.aiOnline ? 'Online & Processing' : 'Offline'}</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1.5rem', marginBottom: '2rem' }}>
        <StatCard title="Total Documents" value={data.documents} icon="▤" variant="blue" />
        <StatCard title="Ready for AI" value={data.readyDocuments} icon="✦" variant="teal" />
        <StatCard title="Monitored Assets" value={data.assets} icon="◎" variant="purple" />
        <StatCard title="Queries Answered" value={data.queries} icon="⌁" variant="amber" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '2rem' }}>
        <div className="card">
          <h2 style={{ marginBottom: '1rem', fontSize: '1.25rem' }}>Monitored Assets</h2>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {(data.assetTags || []).map(tag => (
              <span key={tag} className="badge" style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', fontSize: '0.9rem', padding: '0.5rem 1rem' }}>
                {tag}
              </span>
            ))}
          </div>
        </div>

        <div className="card">
          <h2 style={{ marginBottom: '1rem', fontSize: '1.25rem' }}>Recent Operations</h2>
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {(data.recentQueries || []).map((q: any, i) => (
              <li key={i} style={{ fontSize: '0.9rem', paddingBottom: '1rem', borderBottom: i !== data.recentQueries.length - 1 ? '1px solid var(--border-color)' : 'none' }}>
                <span style={{ color: 'var(--accent-primary)', marginRight: '0.5rem' }}>✦</span>
                {typeof q === 'string' ? q : (q.question || JSON.stringify(q))}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
};
