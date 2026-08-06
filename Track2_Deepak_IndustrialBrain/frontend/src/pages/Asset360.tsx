import React, { useState } from 'react';
import { api } from '../api';
import { AssetData } from '../types';
import { StatCard } from '../components/StatCard';

export const Asset360: React.FC = () => {
  const [tag, setTag] = useState('');
  const [asset, setAsset] = useState<AssetData | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSearch = async () => {
    if (!tag.trim()) return;
    setLoading(true);
    try {
      const data = await api.getAsset(tag.trim());
      setAsset(data);
    } catch (err) {
      alert('Asset not found or error loading data.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container animate-fade-in">
      <div className="hero-section">
        <h1 className="hero-title text-gradient">Asset 360</h1>
        <p className="hero-subtitle">Comprehensive view of equipment health and history.</p>
      </div>

      <div className="card" style={{ marginBottom: '2rem', display: 'flex', gap: '1rem', alignItems: 'center' }}>
        <input 
          type="text" 
          className="input" 
          placeholder="Enter Asset Tag (e.g., P-101)" 
          value={tag} 
          onChange={e => setTag(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          style={{ maxWidth: '300px' }}
        />
        <button className="btn btn-primary" onClick={handleSearch} disabled={loading}>
          {loading ? 'Searching...' : 'Analyze Asset'}
        </button>
      </div>

      {asset && (
        <div className="animate-slide-up">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1.5rem', marginBottom: '2rem' }}>
            <StatCard title="Knowledge Sources" value={(asset.sources || []).length} icon="▤" variant="blue" />
            <StatCard title="Recorded Failures" value={(asset.failures || []).length} icon="⚠" variant="amber" />
            <StatCard title="Maintenance Actions" value={(asset.maintenanceActions || []).length} icon="⚙" variant="purple" />
            <StatCard title="Evidence Chunks" value={asset.evidenceChunks || 0} icon="✦" variant="teal" />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '2rem' }}>
            <div className="card">
              <h3 style={{ marginBottom: '1rem', fontSize: '1.2rem' }}>Operational Timeline</h3>
              <div className="timeline">
                {(asset.timeline || []).map((evt, i) => (
                  <div key={i} className="timeline-item">
                    <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>{new Date(evt.date || Date.now()).toLocaleDateString()}</div>
                    <div style={{ fontWeight: 500 }}>{evt.event || ''}</div>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
              <div className="card">
                <h3 style={{ marginBottom: '1rem', fontSize: '1.2rem' }}>Known Failure Modes</h3>
                <ul style={{ paddingLeft: '1.5rem', color: 'var(--accent-warning)' }}>
                  {(asset.failures || []).map((f, i) => <li key={i} style={{ marginBottom: '0.5rem' }}>{f}</li>)}
                </ul>
              </div>
              <div className="card">
                <h3 style={{ marginBottom: '1rem', fontSize: '1.2rem' }}>Key Measurements</h3>
                {Object.entries(asset.measurements || {}).map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.5rem 0', borderBottom: '1px solid var(--border-color)' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>{k}</span>
                    <span style={{ fontWeight: 600 }}>{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
