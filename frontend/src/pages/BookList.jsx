import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { bookService } from '../services/api';
import BookCard from '../components/BookCard';

const BookList = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  
  // State variables
  const [books, setBooks] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filter, Search, Sort states driven by query parameters
  const searchQuery = searchParams.get('search') || '';
  const selectedCategory = searchParams.get('category') || '';
  const sortBy = searchParams.get('sortBy') || 'title';
  const sortDirection = searchParams.get('direction') || 'asc';
  
  // Local state for immediate inputs
  const [localSearch, setLocalSearch] = useState(searchQuery);

  useEffect(() => {
    // Keep local search matching URL query
    setLocalSearch(searchQuery);
  }, [searchQuery]);

  useEffect(() => {
    // Fetch categories on mount
    const fetchCategories = async () => {
      try {
        const cats = await bookService.getCategories();
        setCategories(cats);
      } catch (err) {
        console.error('Error fetching categories:', err);
      }
    };
    fetchCategories();
  }, []);

  useEffect(() => {
    // Fetch books based on search, filter, and sorting
    const fetchBooks = async () => {
      setLoading(true);
      setError(null);
      try {
        let fetchedBooks = [];
        if (searchQuery.trim()) {
          fetchedBooks = await bookService.searchBooks(searchQuery);
        } else if (selectedCategory) {
          fetchedBooks = await bookService.getBooksByCategory(selectedCategory);
        } else {
          fetchedBooks = await bookService.getBooks(sortBy, sortDirection);
        }

        // Apply in-memory category filter/sorting if searching
        if (searchQuery.trim()) {
          if (selectedCategory) {
            fetchedBooks = fetchedBooks.filter(
              (b) => b.category.toLowerCase() === selectedCategory.toLowerCase()
            );
          }
          // Sort results
          fetchedBooks.sort((a, b) => {
            let valA = a[sortBy] ? a[sortBy].toString().toLowerCase() : '';
            let valB = b[sortBy] ? b[sortBy].toString().toLowerCase() : '';
            if (sortDirection === 'asc') {
              return valA.localeCompare(valB);
            } else {
              return valB.localeCompare(valA);
            }
          });
        }

        setBooks(fetchedBooks);
      } catch (err) {
        console.error('Error loading books:', err);
        setError('Failed to load books. Please check database connectivity.');
      } finally {
        setLoading(false);
      }
    };
    fetchBooks();
  }, [searchQuery, selectedCategory, sortBy, sortDirection]);

  // Handle updates to search/filters
  const handleSearchSubmit = (e) => {
    e.preventDefault();
    updateParams({ search: localSearch });
  };

  const handleCategorySelect = (category) => {
    updateParams({ category, search: '' }); // Clear search when picking a category
  };

  const handleSortChange = (e) => {
    updateParams({ sortBy: e.target.value });
  };

  const handleDirectionToggle = () => {
    const nextDir = sortDirection === 'asc' ? 'desc' : 'asc';
    updateParams({ direction: nextDir });
  };

  const updateParams = (newParams) => {
    const current = Object.fromEntries(searchParams.entries());
    const merged = { ...current, ...newParams };
    
    // Clean up empty params
    Object.keys(merged).forEach((key) => {
      if (!merged[key]) delete merged[key];
    });

    setSearchParams(merged);
  };

  const clearFilters = () => {
    setSearchParams({});
    setLocalSearch('');
  };

  return (
    <div className="container py-5 fade-in">
      <div className="row g-4 mb-5">
        <div className="col-12 text-center text-lg-start d-lg-flex justify-content-between align-items-center">
          <div>
            <div className="section-chip mb-2">Curated catalog</div>
            <h1 className="fw-extrabold heading-font display-6 mb-1">Book Catalog</h1>
            <p className="text-muted mb-0">Browse our collection of technology, engineering, and computer science books.</p>
          </div>
          <button className="btn btn-outline-secondary rounded-pill px-4" onClick={clearFilters}>
            Reset Catalog
          </button>
        </div>
      </div>

      <div className="row g-4">
        <div className="col-lg-3">
          <div className="glass-card p-4 border-0 mb-4">
            <h5 className="fw-bold mb-3 heading-font">Search & filter</h5>

            <form onSubmit={handleSearchSubmit} className="mb-4">
              <label className="form-label text-muted small">Search keyword</label>
              <div className="input-group">
                <input
                  type="text"
                  className="form-control"
                  placeholder="Enter title, author..."
                  value={localSearch}
                  onChange={(e) => setLocalSearch(e.target.value)}
                />
                <button type="submit" className="btn btn-primary">
                  <i className="bi bi-search"></i>
                </button>
              </div>
            </form>

            <div className="mb-4">
              <label className="form-label text-muted small">Sort by</label>
              <div className="d-flex gap-2">
                <select className="form-select" value={sortBy} onChange={handleSortChange}>
                  <option value="title">Book title</option>
                  <option value="author">Author</option>
                  <option value="shelfNumber">Shelf location</option>
                  <option value="quantity">Stock quantity</option>
                  <option value="createdAt">Date added</option>
                </select>
                <button
                  type="button"
                  className="btn btn-outline-secondary px-3"
                  onClick={handleDirectionToggle}
                  title={`Currently: ${sortDirection.toUpperCase()}`}
                >
                  {sortDirection === 'asc' ? <i className="bi bi-sort-up"></i> : <i className="bi bi-sort-down"></i>}
                </button>
              </div>
            </div>

            <div>
              <label className="form-label text-muted small d-block mb-2">Category</label>
              <div className="d-flex flex-column gap-2">
                <button
                  className={`btn btn-sm text-start rounded-3 px-3 py-2 ${!selectedCategory ? 'btn-primary' : 'btn-outline-secondary'}`}
                  onClick={() => handleCategorySelect('')}
                >
                  All categories
                </button>
                {categories.map((cat, idx) => (
                  <button
                    key={idx}
                    className={`btn btn-sm text-start rounded-3 px-3 py-2 ${selectedCategory.toLowerCase() === cat.toLowerCase() ? 'btn-primary' : 'btn-outline-secondary'}`}
                    onClick={() => handleCategorySelect(cat)}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="col-lg-9">
          {loading ? (
            <div className="d-flex justify-content-center align-items-center py-5" style={{ minHeight: '300px' }}>
              <div className="spinner-border" role="status" style={{ width: '3rem', height: '3rem', color: 'var(--primary-color)' }}>
                <span className="visually-hidden">Loading...</span>
              </div>
            </div>
          ) : error ? (
            <div className="glass-card p-5 text-center border-0 text-danger fade-in">
              <i className="bi bi-exclamation-triangle-fill display-3 mb-3 text-warning"></i>
              <h4 className="fw-bold">Connection issue</h4>
              <p className="text-muted">{error}</p>
              <button className="btn btn-primary rounded-pill px-4 mt-3" onClick={() => window.location.reload()}>
                Try again
              </button>
            </div>
          ) : books.length === 0 ? (
            <div className="glass-card p-5 text-center border-0 fade-in">
              <i className="bi bi-book-half display-3 mb-3 text-muted"></i>
              <h4 className="fw-bold">No books found</h4>
              <p className="text-muted">We couldn't find any books matching your filters or search keywords.</p>
              <button className="btn btn-outline-secondary rounded-pill px-4 mt-2" onClick={clearFilters}>
                Clear search
              </button>
            </div>
          ) : (
            <div className="row g-4">
              {books.map((book) => (
                <div className="col-md-6 col-lg-4" key={book.id}>
                  <BookCard book={book} />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default BookList;
