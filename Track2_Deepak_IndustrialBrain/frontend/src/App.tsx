import React, { useState, useEffect } from 'react';
import { LoginForm } from './components/LoginForm';
import { Sidebar } from './components/Sidebar';
import { Topbar } from './components/Topbar';
import { Dashboard } from './pages/Dashboard';
import { KnowledgeLibrary } from './pages/KnowledgeLibrary';
import { AICopilot } from './pages/AICopilot';
import { Asset360 } from './pages/Asset360';
import { RCAIntelligence } from './pages/RCAIntelligence';
import { Analytics } from './pages/Analytics';

function App() {
  const [token, setToken] = useState(localStorage.getItem('token'));
  const [username, setUsername] = useState(localStorage.getItem('username') || '');
  const [currentView, setCurrentView] = useState('dashboard');

  useEffect(() => {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
  }, []);

  const handleLogin = (t: string, u: string) => {
    localStorage.setItem('token', t);
    localStorage.setItem('username', u);
    setToken(t);
    setUsername(u);
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('username');
    setToken(null);
    setUsername('');
  };

  if (!token) {
    return <LoginForm onLogin={handleLogin} />;
  }

  const renderView = () => {
    switch (currentView) {
      case 'dashboard': return <Dashboard />;
      case 'knowledge': return <KnowledgeLibrary />;
      case 'copilot': return <AICopilot />;
      case 'asset360': return <Asset360 />;
      case 'rca': return <RCAIntelligence />;
      case 'analytics': return <Analytics />;
      default: return <Dashboard />;
    }
  };

  const titles: Record<string, string> = {
    dashboard: 'Dashboard',
    knowledge: 'Knowledge Base',
    copilot: 'AI Copilot',
    asset360: 'Asset 360',
    rca: 'RCA Intelligence',
    analytics: 'Analytics'
  };

  return (
    <div className="app-container">
      <Sidebar currentView={currentView} onChangeView={setCurrentView} onLogout={handleLogout} />
      <div className="main-content">
        <Topbar title={titles[currentView] || ''} username={username} />
        <main style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          {renderView()}
        </main>
      </div>
    </div>
  );
}

export default App;
