import React from 'react';
import { ChatPanel } from '../components/ChatPanel';

export const AICopilot: React.FC = () => {
  return (
    <div className="page-container animate-fade-in" style={{ height: 'calc(100vh - 64px)', display: 'flex', flexDirection: 'column' }}>
      <div className="hero-section" style={{ marginBottom: '1.5rem' }}>
        <h1 className="hero-title text-gradient">Ask the operation.</h1>
        <p className="hero-subtitle">Real-time answers powered by your knowledge base.</p>
      </div>
      
      <div style={{ flex: 1, minHeight: 0 }}>
        <ChatPanel />
      </div>
    </div>
  );
};
