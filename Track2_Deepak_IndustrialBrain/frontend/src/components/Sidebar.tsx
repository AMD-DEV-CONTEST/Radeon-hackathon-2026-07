import React from 'react';

interface SidebarProps {
  currentView: string;
  onChangeView: (view: string) => void;
  onLogout: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentView, onChangeView, onLogout }) => {
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: '⌂' },
    { id: 'knowledge', label: 'Knowledge Base', icon: '▤' },
    { id: 'copilot', label: 'AI Copilot', icon: '✦' },
    { id: 'asset360', label: 'Asset 360', icon: '◎' },
    { id: 'rca', label: 'RCA Intelligence', icon: '⌁' },
    { id: 'analytics', label: 'Analytics', icon: '▲' }
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon">✦</div>
        <div>
          <h1>IndusMind</h1>
          <div className="sidebar-brand-sub">Industrial AI</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {navItems.map(item => {
          const isActive = currentView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onChangeView(item.id)}
              className={`nav-item ${isActive ? 'active' : ''}`}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <button className="nav-item" onClick={onLogout} style={{ color: 'var(--accent-danger)' }}>
          <span className="nav-icon">○</span>
          <span>Sign Out</span>
        </button>
      </div>
    </aside>
  );
};
