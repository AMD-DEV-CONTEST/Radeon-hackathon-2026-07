import React, { useEffect, useState } from 'react';

interface TopbarProps {
  title: string;
  username: string;
}

export const Topbar: React.FC<TopbarProps> = ({ title, username }) => {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (localStorage.getItem('theme') as 'dark' | 'light') || 'dark';
  });

  useEffect(() => {
    if (theme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => (prev === 'dark' ? 'light' : 'dark'));
  };

  return (
    <header className="topbar">
      <div className="topbar-left">
        <h2 className="topbar-title">{title}</h2>
        <div className="topbar-status">
          <span className="topbar-status-dot"></span>
          <span>System Online</span>
        </div>
      </div>

      <div className="topbar-right">
        <button
          className="theme-toggle"
          onClick={toggleTheme}
          title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
          aria-label="Toggle Theme"
        >
          {theme === 'dark' ? '☀' : '☾'}
        </button>

        <span className="topbar-date">
          {new Date().toLocaleDateString('en-US', {
            weekday: 'short',
            year: 'numeric',
            month: 'short',
            day: 'numeric',
          })}
        </span>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
          <div className="topbar-avatar">
            {username.charAt(0).toUpperCase()}
          </div>
          <span className="topbar-username">{username}</span>
        </div>
      </div>
    </header>
  );
};
