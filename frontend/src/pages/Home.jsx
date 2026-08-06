import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { bookService } from '../services/api';

const Home = () => {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState('');
  const [stats, setStats] = useState({
    totalBooks: 0,
    availableBooks: 0,
    borrowedBooks: 0,
    totalCategories: 0,
    recentBooks: []
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const data = await bookService.getLibraryStats();
        setStats(data);
      } catch (err) {
        console.error('Error fetching statistics:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchStats();
  }, []);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      navigate(`/books?search=${encodeURIComponent(searchQuery)}`);
    }
  };

  const categories = [
    { name: 'Java', icon: 'bi-filetype-java', color: 'bg-primary' },
    { name: 'Python', icon: 'bi-filetype-py', color: 'bg-warning text-dark' },
    { name: 'Backend', icon: 'bi-server', color: 'bg-success' },
    { name: 'Frontend', icon: 'bi-code-slash', color: 'bg-info text-dark' },
    { name: 'Database', icon: 'bi-database-fill', color: 'bg-danger' },
    { name: 'AI', icon: 'bi-cpu-fill', color: 'bg-purple' },
    { name: 'Machine Learning', icon: 'bi-graph-up-arrow', color: 'bg-dark' },
    { name: 'Software Engineering', icon: 'bi-gear-fill', color: 'bg-secondary' }
  ];

  return (
    <div className="container py-5 position-relative fade-in">
      <div className="orb orb-1"></div>
      <div className="orb orb-2"></div>

      <div className="row align-items-center justify-content-between mb-5 py-4 g-5">
        <div className="col-lg-6">
          <div className="section-chip mb-3">
            <i className="bi bi-stars"></i> Meet LibriAI, your smart librarian
          </div>
          <h1 className="display-4 fw-extrabold heading-font mb-3">
            Discover your next great read with <span className="gradient-text">AI guidance</span>
          </h1>
          <p className="lead text-muted mb-4">
            Search the catalog, check live availability, find shelf locations, and ask the assistant for focused recommendations in seconds.
          </p>

          <form onSubmit={handleSearchSubmit} className="d-flex gap-2 p-2 glass-card rounded-pill mb-4" style={{ maxWidth: '560px' }}>
            <input
              type="text"
              className="form-control border-0 rounded-pill px-4 bg-transparent"
              placeholder="Search by title, author, category, or topic..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{ boxShadow: 'none' }}
            />
            <button type="submit" className="btn btn-primary rounded-pill px-4">
              <i className="bi bi-search"></i>
            </button>
          </form>

          <div className="d-flex flex-wrap gap-3">
            <Link to="/ai-chat" className="btn btn-primary btn-lg rounded-pill px-4 d-flex align-items-center gap-2">
              <i className="bi bi-robot"></i> Chat with AI
            </Link>
            <Link to="/books" className="btn btn-outline-secondary btn-lg rounded-pill px-4">
              Browse Catalog
            </Link>
          </div>
        </div>

        <div className="col-lg-5 text-center d-none d-lg-block">
          <div className="glass-card p-4 rounded-4 position-relative">
            <img
              src="https://images.unsplash.com/photo-1507842217343-583bb7270b66?q=80&w=600"
              alt="Library shelves"
              className="img-fluid rounded-3 shadow-lg"
              style={{ maxHeight: '340px', objectFit: 'cover', width: '100%' }}
            />
            <div className="position-absolute top-100 start-0 translate-middle glass-card p-3 rounded-3 d-flex align-items-center gap-3 hover-scale border-0 shadow">
              <div className="rounded-circle p-3" style={{ background: 'rgba(47, 158, 104, 0.16)', color: 'var(--success-color)' }}>
                <i className="bi bi-patch-check-fill fs-4"></i>
              </div>
              <div className="text-start">
                <h6 className="fw-bold mb-0">Live inventory</h6>
                <small className="text-muted">Real-time shelf sync</small>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="row g-4 mb-5 text-center">
        {[
          { icon: 'bi-book', value: stats.totalBooks, label: 'Total titles', tone: 'var(--primary-color)' },
          { icon: 'bi-bookmark-check', value: stats.availableBooks, label: 'Available now', tone: 'var(--success-color)' },
          { icon: 'bi-bookmark-dash', value: stats.borrowedBooks, label: 'Borrowed / out', tone: 'var(--warning-color)' },
          { icon: 'bi-grid', value: stats.totalCategories, label: 'Categories', tone: 'var(--accent-color)' }
        ].map((stat, idx) => (
          <div className="col-md-3 col-6" key={idx}>
            <div className="glass-card p-4 h-100 border-0 shadow-sm">
              <div className="rounded-circle p-3 d-inline-flex mb-3" style={{ background: 'rgba(31, 111, 102, 0.12)', color: stat.tone }}>
                <i className={`bi ${stat.icon} fs-3`}></i>
              </div>
              <h2 className="fw-extrabold heading-font mb-1">{loading ? '...' : stat.value}</h2>
              <p className="text-muted mb-0">{stat.label}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="mb-5">
        <div className="d-flex align-items-center justify-content-between mb-4">
          <h2 className="heading-font fw-bold mb-0 d-flex align-items-center gap-2">
            <i className="bi bi-tag" style={{ color: 'var(--primary-color)' }}></i> Popular categories
          </h2>
        </div>
        <div className="row g-3">
          {categories.map((cat, idx) => (
            <div className="col-lg-3 col-md-4 col-sm-6" key={idx}>
              <Link
                to={`/books?category=${encodeURIComponent(cat.name)}`}
                className="d-flex align-items-center gap-3 p-3 glass-card text-decoration-none hover-scale h-100"
              >
                <div className={`rounded-3 p-3 d-flex align-items-center justify-content-center text-white ${cat.color}`} style={{ width: '50px', height: '50px' }}>
                  <i className={`bi ${cat.icon} fs-4`}></i>
                </div>
                <div>
                  <h6 className="fw-bold text-truncate mb-0">{cat.name}</h6>
                  <small className="text-muted">Explore books</small>
                </div>
              </Link>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="d-flex justify-content-between align-items-center mb-4">
          <h2 className="heading-font fw-bold mb-0 d-flex align-items-center gap-2">
            <i className="bi bi-clock-history" style={{ color: 'var(--primary-color)' }}></i> Recently added
          </h2>
          <Link to="/books" className="btn btn-link text-decoration-none" style={{ color: 'var(--primary-color)' }}>
            View all catalog <i className="bi bi-arrow-right"></i>
          </Link>
        </div>

        {loading ? (
          <div className="text-center py-5">
            <div className="spinner-border" role="status" style={{ color: 'var(--primary-color)' }}>
              <span className="visually-hidden">Loading...</span>
            </div>
          </div>
        ) : (
          <div className="row g-4">
            {stats.recentBooks && stats.recentBooks.length > 0 ? (
              stats.recentBooks.map((book) => (
                <div className="col-lg-4 col-md-6" key={book.id}>
                  <div className="card glass-card h-100 border-0 overflow-hidden d-flex flex-row p-3 hover-scale">
                    <div style={{ width: '90px', height: '120px', flexShrink: 0, overflow: 'hidden', borderRadius: '10px' }}>
                      <img
                        src={book.imageUrl || `https://images.unsplash.com/photo-1543002588-bfa74002ed7e?q=80&w=300`}
                        alt={book.title}
                        className="w-100 h-100 object-fit-cover"
                        onError={(e) => {
                          e.target.src = `https://images.unsplash.com/photo-1543002588-bfa74002ed7e?q=80&w=300`;
                        }}
                      />
                    </div>
                    <div className="ps-3 d-flex flex-column justify-content-between w-100 overflow-hidden">
                      <div>
                        <span className="badge rounded-pill px-2 py-0.5 mb-1" style={{ background: 'rgba(31, 111, 102, 0.12)', color: 'var(--primary-color)', fontSize: '0.75rem' }}>
                          {book.category}
                        </span>
                        <h6 className="fw-bold mb-1 text-truncate" title={book.title}>{book.title}</h6>
                        <small className="text-muted d-block text-truncate">by {book.author}</small>
                      </div>
                      <div className="d-flex justify-content-between align-items-center pt-2">
                        <small className="text-muted"><i className="bi bi-geo-alt-fill" style={{ color: 'var(--accent-color)' }}></i> {book.shelfNumber}</small>
                        <Link to={`/books/${book.id}`} className="btn btn-primary rounded-pill py-1 px-2" style={{ fontSize: '0.75rem' }}>
                          Open
                        </Link>
                      </div>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="col-12 text-center text-muted py-4">No books added recently.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default Home;
