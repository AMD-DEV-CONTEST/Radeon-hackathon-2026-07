import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

const AdminLogin = () => {
  const navigate = useNavigate();
  const [credentials, setCredentials] = useState({ username: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setCredentials((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    // Simulated authentications - standard credential: admin / admin
    setTimeout(() => {
      if (credentials.username === 'admin' && credentials.password === 'admin') {
        localStorage.setItem('isAdmin', 'true');
        window.dispatchEvent(new Event('storage')); // Alert other components
        navigate('/admin');
      } else {
        setError('Invalid username or password. Try admin / admin.');
      }
      setLoading(false);
    }, 800);
  };

  return (
    <div className="container py-5 d-flex align-items-center justify-content-center position-relative" style={{ minHeight: '75vh' }}>
      <div className="orb orb-1"></div>
      <div className="orb orb-2"></div>

      <div className="card glass-card border-0 p-4 p-md-5 rounded-4 shadow-lg w-100" style={{ maxWidth: '420px' }}>
        <div className="text-center mb-4">
          <div className="gradient-bg d-inline-flex align-items-center justify-content-center rounded-circle mb-3" style={{ width: '60px', height: '60px' }}>
            <i className="bi bi-shield-lock-fill text-white fs-3"></i>
          </div>
          <h3 className="fw-bold heading-font mb-1">Librarian login</h3>
          <p className="text-muted small">Access the inventory and shelf management system</p>
        </div>

        {error && (
          <div className="alert alert-danger rounded-3 p-2 small text-center mb-3" role="alert">
            <i className="bi bi-exclamation-circle-fill me-1"></i> {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="mb-3">
            <label className="form-label text-muted small">Username</label>
            <input
              type="text"
              name="username"
              className="form-control"
              placeholder="Enter username"
              value={credentials.username}
              onChange={handleChange}
              required
            />
          </div>
          <div className="mb-4">
            <label className="form-label text-muted small">Password</label>
            <input
              type="password"
              name="password"
              className="form-control"
              placeholder="Enter password"
              value={credentials.password}
              onChange={handleChange}
              required
            />
          </div>
          <button type="submit" className="btn btn-primary w-100 py-2.5 rounded-3 d-flex align-items-center justify-content-center gap-2" disabled={loading}>
            {loading ? (
              <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
            ) : (
              <>
                <i className="bi bi-box-arrow-in-right"></i> Sign in
              </>
            )}
          </button>
        </form>

        <div className="text-center mt-3 text-muted small">
          Demo login: <span className="badge rounded-pill" style={{ background: 'rgba(31, 111, 102, 0.12)', color: 'var(--primary-color)' }}>admin / admin</span>
        </div>
      </div>
    </div>
  );
};

export default AdminLogin;
