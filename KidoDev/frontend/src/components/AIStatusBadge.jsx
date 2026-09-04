import React, { useState, useEffect } from 'react';
import { fetchBackendHealth, getBackendArchitectureInfo } from '../agents/AgentOrchestrator';

export default function AIStatusBadge({ compact = false }) {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const info = getBackendArchitectureInfo();

  useEffect(() => {
    let isMounted = true;
    async function checkStatus() {
      const res = await fetchBackendHealth();
      if (isMounted) {
        setHealth(res);
        setLoading(false);
      }
    }
    checkStatus();
    const timer = setInterval(checkStatus, 30_000);
    return () => {
      isMounted = false;
      clearInterval(timer);
    };
  }, []);

  const isOnline = health !== null;

  if (compact) {
    return (
      <div
        title={`Stack: React -> ngrok -> FastAPI -> Qwen on AMD GPU (${isOnline ? 'Online' : 'Offline'})`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 10px',
          borderRadius: 20,
          background: isOnline ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)',
          border: `1px solid ${isOnline ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
          fontSize: 11,
          fontWeight: 700,
          color: isOnline ? '#15803D' : '#B91C1C',
        }}
      >
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: isOnline ? '#22C55E' : '#EF4444',
            boxShadow: isOnline ? '0 0 8px #22C55E' : 'none',
          }}
        />
        <span>{isOnline ? 'Qwen on AMD GPU' : 'AI Offline'}</span>
      </div>
    );
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 14px',
        borderRadius: 14,
        background: '#0F172A',
        border: '1px solid #1E293B',
        color: '#F8FAFC',
        fontFamily: 'sans-serif',
        boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 800, color: '#38BDF8' }}>React</span>
        <span style={{ color: '#64748B', fontSize: 11 }}>➔</span>
        <span style={{ fontSize: 13, fontWeight: 800, color: '#F59E0B' }}>ngrok</span>
        <span style={{ color: '#64748B', fontSize: 11 }}>➔</span>
        <span style={{ fontSize: 13, fontWeight: 800, color: '#10B981' }}>FastAPI</span>
        <span style={{ color: '#64748B', fontSize: 11 }}>➔</span>
        <span style={{ fontSize: 13, fontWeight: 800, color: '#EC4899' }}>Qwen AMD GPU</span>
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          padding: '2px 8px',
          borderRadius: 10,
          background: isOnline ? '#14532D' : '#7F1D1D',
          color: isOnline ? '#86EFAC' : '#FCA5A5',
          fontSize: 10,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
        }}
      >
        <span
          style={{
            width: 5,
            height: 5,
            borderRadius: '50%',
            background: isOnline ? '#4ADE80' : '#F87171',
          }}
        />
        {loading ? 'Checking...' : isOnline ? 'Connected' : 'Offline'}
      </div>
    </div>
  );
}
