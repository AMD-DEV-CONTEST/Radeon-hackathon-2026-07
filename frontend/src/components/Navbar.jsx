import React from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';

const Navbar = ({ darkMode, toggleDarkMode }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const isAdmin = localStorage.getItem('isAdmin') === 'true';

  const handleLogout = () => {
    localStorage.removeItem('isAdmin');
    navigate('/');
    window.dispatchEvent(new Event('storage'));
  };

  const isActive = (path) => (location.pathname === path ? 'active' : '');

  return (
    <nav className="navbar navbar-expand-lg glass-navbar py-3">
      <div className="container">
        <Link className="navbar-brand d-flex align-items-center gap-2" to="/">
          <div className="gradient-bg d-flex align-items-center justify-content-center rounded-circle" style={{ width: '42px', height: '42px' }}>
            <i className="bi bi-book-half text-white fs-5"></i>
          </div>
          <span className="heading-font fw-bold fs-4" style={{ color: 'var(--text-color)' }}>
            Libri<span className="gradient-text">AI</span>
          </span>
        </Link>

        <button
          className="navbar-toggler border-0"
          type="button"
          data-bs-toggle="collapse"
          data-bs-target="#navbarNav"
          aria-controls="navbarNav"
          aria-expanded="false"
          aria-label="Toggle navigation"
        >
          <span className="navbar-toggler-icon"></span>
        </button>

        <div className="collapse navbar-collapse" id="navbarNav">
          <ul className="navbar-nav me-auto mb-2 mb-lg-0 gap-1 ms-lg-3">
            <li className="nav-item">
              <Link className={`nav-link px-3 rounded-pill ${isActive('/')}`} to="/">Home</Link>
            </li>
            <li className="nav-item">
              <Link className={`nav-link px-3 rounded-pill ${isActive('/search')}`} to="/search">Search</Link>
            </li>
            <li className="nav-item">
              <Link className={`nav-link px-3 rounded-pill ${isActive('/books')}`} to="/books">Book Catalog</Link>
            </li>
            <li className="nav-item">
              <Link className={`nav-link px-3 rounded-pill ${isActive('/ai-chat')}`} to="/ai-chat">
                <i className="bi bi-robot me-1"></i> AI Assistant
              </Link>
            </li>
            <li className="nav-item">
              <Link className={`nav-link px-3 rounded-pill ${isActive('/faq')}`} to="/faq">FAQs</Link>
            </li>
          </ul>

          <div className="d-flex align-items-center gap-2 mt-3 mt-lg-0">
            <button
              className="btn btn-link p-2 theme-switch"
              onClick={toggleDarkMode}
              title={darkMode ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
            >
              {darkMode ? (
                <i className="bi bi-sun-fill text-warning fs-5"></i>
              ) : (
                <i className="bi bi-moon-stars-fill fs-5" style={{ color: 'var(--primary-color)' }}></i>
              )}
            </button>

            {isAdmin ? (
              <>
                <Link className="btn btn-outline-secondary rounded-pill px-3 d-flex align-items-center gap-2" to="/admin">
                  <i className="bi bi-grid-1x2-fill"></i> Admin
                </Link>
                <button className="btn btn-primary rounded-pill px-3" onClick={handleLogout}>
                  Logout
                </button>
              </>
            ) : (
              <Link className="btn btn-primary rounded-pill px-3" to="/admin-login">
                Librarian Portal
              </Link>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
