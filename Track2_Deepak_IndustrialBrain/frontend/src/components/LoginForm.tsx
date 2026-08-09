import React, { useState } from 'react';
import { api } from '../api';

interface LoginFormProps {
  onLogin: (token: string, username: string) => void;
}

export const LoginForm: React.FC<LoginFormProps> = ({ onLogin }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const res = await api.login({ username, password });
      onLogin(res.token, res.displayName || res.username);
    } catch (err) {
      setError('Invalid credentials or system offline.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-bg"></div>
      <div className="login-card">
        <div className="login-logo">✦</div>
        <h1 className="login-title">IndusMind AI</h1>
        <p className="login-subtitle">Industrial Intelligence Core</p>
        
        <form onSubmit={handleSubmit} className="login-form">
          {error && <div className="login-error">{error}</div>}
          
          <div className="login-field">
            <label className="login-label">Username</label>
            <input
              type="text"
              className="input"
              placeholder="e.g. admin or engineer"
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
            />
          </div>
          
          <div className="login-field">
            <label className="login-label">Password</label>
            <input
              type="password"
              className="input"
              placeholder="Enter password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>
          
          <button type="submit" className="btn btn-primary" style={{ width: '100%', padding: '0.75rem', marginTop: '0.5rem', fontSize: '1rem' }} disabled={loading}>
            {loading ? <div className="spinner" style={{ margin: '0 auto' }}></div> : 'Sign In to Workspace'}
          </button>
        </form>
      </div>
    </div>
  );
};
