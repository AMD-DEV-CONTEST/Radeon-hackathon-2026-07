import React, { useState } from 'react';
import { api } from '../api';
import { RcaData } from '../types';

export const RCAIntelligence: React.FC = () => {
  const [tag, setTag] = useState('');
  const [rca, setRca] = useState<RcaData | null>(null);
  const [loading, setLoading] = useState(false);

  const handleGenerate = async () => {
    if (!tag.trim()) return;
    setLoading(true);
    try {
      const data = await api.generateRca(tag.trim());
      setRca(data);
    } catch (err) {
      alert('Failed to generate RCA.');
    } finally {
      setLoading(false);
    }
  };

  const handleExport = () => {
    if (rca) api.exportRca(rca.tag);
  };

  return (
    <div className="page-container animate-fade-in">
      <div className="hero-section">
        <h1 className="hero-title text-gradient">Automated RCA</h1>
        <p className="hero-subtitle">Generate root cause analysis reports instantly from historical data.</p>
      </div>

      <div className="card" style={{ marginBottom: '2rem', display: 'flex', gap: '1rem', alignItems: 'center' }}>
        <input 
          type="text" 
          className="input" 
          placeholder="Enter Asset Tag (e.g., P-101)" 
          value={tag} 
          onChange={e => setTag(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleGenerate()}
          style={{ maxWidth: '300px' }}
        />
        <button className="btn btn-primary" onClick={handleGenerate} disabled={loading}>
          {loading ? 'Analyzing...' : 'Generate RCA Report'}
        </button>
      </div>

      {rca && (
        <div className="card animate-slide-up" style={{ padding: '2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '2rem', paddingBottom: '1rem', borderBottom: '1px solid var(--border-color)' }}>
            <div>
              <h2 style={{ fontSize: '1.8rem', color: 'var(--accent-primary)', marginBottom: '0.5rem' }}>RCA: {rca.tag}</h2>
              <div className="badge badge-success">Confidence: {Math.round(rca.confidenceScore * 100)}%</div>
            </div>
            <button className="btn btn-secondary" onClick={handleExport}>
              Download DOCX
            </button>
          </div>

          <div style={{ marginBottom: '2rem' }}>
            <h3 style={{ fontSize: '1.2rem', marginBottom: '1rem', color: 'var(--accent-danger)' }}>Root Cause</h3>
            <p style={{ fontSize: '1.1rem', background: 'rgba(239, 68, 68, 0.1)', padding: '1rem', borderRadius: '8px', borderLeft: '4px solid var(--accent-danger)' }}>
              {rca.rootCause}
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
            <div>
              <h3 style={{ fontSize: '1.2rem', marginBottom: '1rem', color: 'var(--accent-warning)' }}>Contributing Factors</h3>
              <ul style={{ paddingLeft: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {(rca.contributingFactors || []).map((f, i) => <li key={i}>{f}</li>)}
              </ul>
            </div>
            <div>
              <h3 style={{ fontSize: '1.2rem', marginBottom: '1rem', color: 'var(--accent-primary)' }}>Recommendations</h3>
              <ul style={{ paddingLeft: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {(rca.recommendations || []).map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
