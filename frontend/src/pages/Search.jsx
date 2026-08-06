import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { bookService } from '../services/api';

const Search = () => {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (query.trim().length < 2) {
      setSuggestions([]);
      return;
    }

    const fetchSuggestions = async () => {
      setLoading(true);
      try {
        const results = await bookService.searchBooks(query);
        // Limit to 5 suggestions
        setSuggestions(results.slice(0, 5));
      } catch (err) {
        console.error('Error fetching suggestions:', err);
      } finally {
        setLoading(false);
      }
    };

    const timer = setTimeout(() => {
      fetchSuggestions();
    }, 300); // Debounce API requests

    return () => clearTimeout(timer);
  }, [query]);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    if (query.trim()) {
      navigate(`/books?search=${encodeURIComponent(query)}`);
    }
  };

  const sampleCategories = ['Java', 'Python', 'Database', 'Backend', 'Frontend', 'AI'];
  const popularKeywords = ['Clean Code', 'Spring', 'Algorithms', 'Machine Learning', 'Tanenbaum'];

  return (
    <div className="container py-5 position-relative fade-in" style={{ minHeight: '80vh' }}>
      <div className="orb orb-1"></div>
      <div className="orb orb-2"></div>

      <div className="row justify-content-center mt-4">
        <div className="col-lg-8 text-center">
          <div className="badge bg-primary bg-opacity-25 text-primary rounded-pill px-3 py-2 mb-3">
            🔍 Advanced Search Engine
          </div>
          <h1 className="fw-extrabold heading-font display-5 mb-3">Find Library Resources</h1>
          <p className="text-muted mb-5">Search across titles, authors, categories, or ISBN numbers with real-time suggestions.</p>

          {/* Search Form */}
          <div className="position-relative mb-5" style={{ maxWidth: '650px', margin: '0 auto' }}>
            <form onSubmit={handleSearchSubmit} className="d-flex gap-2 p-2 glass-card rounded-pill shadow-sm">
              <input 
                type="text" 
                className="form-control border-0 rounded-pill px-4 bg-transparent text-white" 
                placeholder="Type book title, author, or keyword..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                style={{ boxShadow: 'none' }}
                autoComplete="off"
              />
              <button type="submit" className="btn btn-primary rounded-pill px-4" style={{ minWidth: '80px' }}>
                {loading ? (
                  <span className="spinner-border spinner-border-sm" role="status"></span>
                ) : (
                  <i className="bi bi-search"></i>
                )}
              </button>
            </form>

            {/* Auto-suggest dropdown (Search Suggestions) */}
            {suggestions.length > 0 && (
              <div className="position-absolute start-0 end-0 mt-2 glass-card border-0 rounded-4 shadow-lg overflow-hidden text-start z-3" style={{ maxHeight: '350px' }}>
                <div className="p-2 border-bottom border-secondary border-opacity-10 bg-dark bg-opacity-25">
                  <small className="text-muted ms-2">Real-time Search Suggestions</small>
                </div>
                <div className="list-group list-group-flush bg-transparent">
                  {suggestions.map((book) => (
                    <Link 
                      key={book.id} 
                      to={`/books/${book.id}`}
                      className="list-group-item list-group-item-action bg-transparent border-0 border-bottom border-secondary border-opacity-10 py-3 px-4 text-white d-flex align-items-center justify-content-between hover-scale"
                    >
                      <div className="d-flex align-items-center gap-3 overflow-hidden">
                        <img 
                          src={book.imageUrl || `https://images.unsplash.com/photo-1543002588-bfa74002ed7e?q=80&w=50`} 
                          alt="" 
                          style={{ width: '32px', height: '44px', objectFit: 'cover', borderRadius: '4px' }}
                          onError={(e) => e.target.src = `https://images.unsplash.com/photo-1543002588-bfa74002ed7e?q=80&w=50`}
                        />
                        <div className="overflow-hidden">
                          <h6 className="fw-bold mb-0 text-truncate" style={{ fontSize: '0.9rem' }}>{book.title}</h6>
                          <small className="text-muted d-block text-truncate">by {book.author}</small>
                        </div>
                      </div>
                      <span className="badge bg-secondary text-white rounded-pill px-2.5 py-1" style={{ fontSize: '0.75rem' }}>
                        {book.category}
                      </span>
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Quick Keywords */}
          <div className="mb-4">
            <h6 className="text-muted small heading-font text-uppercase mb-3" style={{ letterSpacing: '1px' }}>Popular Searches</h6>
            <div className="d-flex flex-wrap justify-content-center gap-2">
              {popularKeywords.map((kw, idx) => (
                <button 
                  key={idx}
                  className="btn btn-sm btn-outline-secondary rounded-pill px-3 py-1.5"
                  onClick={() => { setQuery(kw); navigate(`/books?search=${encodeURIComponent(kw)}`); }}
                >
                  {kw}
                </button>
              ))}
            </div>
          </div>

          {/* Category Quicklinks */}
          <div>
            <h6 className="text-muted small heading-font text-uppercase mb-3" style={{ letterSpacing: '1px' }}>Explore Categories</h6>
            <div className="d-flex flex-wrap justify-content-center gap-2">
              {sampleCategories.map((cat, idx) => (
                <Link 
                  key={idx}
                  to={`/books?category=${encodeURIComponent(cat)}`}
                  className="btn btn-sm btn-outline-primary rounded-pill px-3 py-1.5"
                >
                  {cat}
                </Link>
              ))}
            </div>
          </div>

        </div>
      </div>
    </div>
  );
};

export default Search;
