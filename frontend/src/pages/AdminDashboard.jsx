import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { bookService } from '../services/api';

const AdminDashboard = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState({
    totalBooks: 0,
    availableBooks: 0,
    borrowedBooks: 0,
    totalCategories: 0
  });
  const [books, setBooks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [toast, setToast] = useState(null);

  // Authenticate admin check
  useEffect(() => {
    const isAdmin = localStorage.getItem('isAdmin') === 'true';
    if (!isAdmin) {
      navigate('/admin-login');
    }
  }, [navigate]);

  const loadData = async () => {
    setLoading(true);
    try {
      const currentStats = await bookService.getLibraryStats();
      setStats(currentStats);
      
      const allBooks = await bookService.getBooks();
      setBooks(allBooks);
    } catch (err) {
      console.error(err);
      showToast('error', 'Failed to retrieve inventory data from backend.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const showToast = (type, message) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 4000);
  };

  const handleDelete = async (id, title) => {
    if (window.confirm(`Are you sure you want to permanently delete "${title}"?`)) {
      try {
        await bookService.deleteBook(id);
        showToast('success', `"${title}" has been successfully deleted.`);
        loadData(); // Reload inventory
      } catch (err) {
        console.error(err);
        showToast('error', `Failed to delete "${title}".`);
      }
    }
  };

  // Filter books matching search keyword
  const filteredBooks = books.filter(
    (b) =>
      b.title.toLowerCase().includes(search.toLowerCase()) ||
      b.author.toLowerCase().includes(search.toLowerCase()) ||
      b.isbn.toLowerCase().includes(search.toLowerCase()) ||
      b.category.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="container py-5 fade-in">
      {toast && (
        <div className="toast-container-custom">
          <div className={`toast-custom border-start border-4 ${toast.type === 'success' ? 'border-success' : 'border-danger'}`}>
            <div className="d-flex align-items-center gap-2">
              <i className={`bi ${toast.type === 'success' ? 'bi-check-circle-fill text-success' : 'bi-exclamation-triangle-fill text-danger'} fs-4`}></i>
              <div>
                <h6 className="fw-bold mb-0">{toast.type === 'success' ? 'Success' : 'Error'}</h6>
                <small className="text-muted">{toast.message}</small>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="d-flex flex-column flex-md-row justify-content-between align-items-md-center gap-3 mb-5">
        <div>
          <div className="section-chip mb-2">Inventory control</div>
          <h1 className="fw-extrabold heading-font display-6 mb-1">Librarian dashboard</h1>
          <p className="text-muted mb-0">Monitor availability, update records, and manage the catalog in one place.</p>
        </div>
        <Link to="/admin/add-book" className="btn btn-primary rounded-pill px-4 d-flex align-items-center gap-2">
          <i className="bi bi-plus-lg"></i> Add new book
        </Link>
      </div>

      <div className="row g-4 mb-5">
        {[
          { label: 'Total titles', value: stats.totalBooks, tone: 'var(--primary-color)' },
          { label: 'Available', value: stats.availableBooks, tone: 'var(--success-color)' },
          { label: 'Borrowed / out', value: stats.borrowedBooks, tone: 'var(--danger-color)' },
          { label: 'Categories', value: stats.totalCategories, tone: 'var(--accent-color)' }
        ].map((stat, idx) => (
          <div className="col-md-3 col-6" key={idx}>
            <div className="glass-card p-4 border-0 shadow-sm text-center">
              <h4 className="text-muted heading-font small text-uppercase">{stat.label}</h4>
              <h2 className="fw-extrabold mb-0 mt-2" style={{ color: stat.tone }}>{stat.value}</h2>
            </div>
          </div>
        ))}
      </div>

      <div className="glass-card p-4 border-0 shadow-sm">
        <div className="d-flex flex-column flex-md-row justify-content-between align-items-md-center gap-3 mb-4">
          <h4 className="fw-bold heading-font mb-0">Book inventory</h4>

          <div className="d-flex gap-2" style={{ maxWidth: '360px', width: '100%' }}>
            <input
              type="text"
              className="form-control rounded-pill px-3 py-2"
              placeholder="Filter by title, author, ISBN..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        {loading ? (
          <div className="text-center py-5">
            <div className="spinner-border" role="status" style={{ color: 'var(--primary-color)' }}>
              <span className="visually-hidden">Loading...</span>
            </div>
          </div>
        ) : filteredBooks.length === 0 ? (
          <div className="text-center py-5 text-muted">
            <i className="bi bi-folder-x display-4"></i>
            <p className="mt-2">No matching books found in inventory.</p>
          </div>
        ) : (
          <div className="table-responsive">
            <table className="table align-middle text-muted" style={{ borderCollapse: 'separate', borderSpacing: '0 8px' }}>
              <thead>
                <tr>
                  <th style={{ width: '80px' }}>Cover</th>
                  <th>Title & author</th>
                  <th>Category</th>
                  <th>ISBN</th>
                  <th>Shelf</th>
                  <th>Qty</th>
                  <th>Status</th>
                  <th className="text-end" style={{ width: '150px' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredBooks.map((book) => (
                  <tr key={book.id} className="border-bottom border-secondary border-opacity-10">
                    <td>
                      <img
                        src={book.imageUrl || `https://images.unsplash.com/photo-1543002588-bfa74002ed7e?q=80&w=100`}
                        alt={book.title}
                        className="rounded"
                        style={{ width: '45px', height: '60px', objectFit: 'cover' }}
                        onError={(e) => {
                          e.target.src = `https://images.unsplash.com/photo-1543002588-bfa74002ed7e?q=80&w=100`;
                        }}
                      />
                    </td>
                    <td>
                      <div className="fw-bold mb-0 text-truncate" style={{ maxWidth: '240px', color: 'var(--text-color)' }}>{book.title}</div>
                      <small className="text-muted">by {book.author}</small>
                    </td>
                    <td><span className="badge rounded-pill px-2.5 py-1" style={{ background: 'rgba(31, 111, 102, 0.12)', color: 'var(--primary-color)', fontSize: '0.8rem' }}>{book.category}</span></td>
                    <td><code style={{ color: 'var(--accent-color)' }}>{book.isbn || 'N/A'}</code></td>
                    <td><strong style={{ color: 'var(--text-color)' }}>{book.shelfNumber}</strong></td>
                    <td style={{ color: 'var(--text-color)' }}>{book.quantity}</td>
                    <td>
                      <span className={`badge rounded-pill ${book.availability ? 'bg-success bg-opacity-25 text-success' : 'bg-danger bg-opacity-25 text-danger'}`}>
                        {book.availability ? 'Available' : 'Out'}
                      </span>
                    </td>
                    <td className="text-end">
                      <div className="d-flex justify-content-end gap-2">
                        <Link to={`/admin/edit-book/${book.id}`} className="btn btn-sm btn-outline-secondary rounded-circle d-flex align-items-center justify-content-center" style={{ width: '32px', height: '32px', padding: 0 }} title="Edit">
                          <i className="bi bi-pencil-fill"></i>
                        </Link>
                        <button className="btn btn-sm btn-outline-danger rounded-circle d-flex align-items-center justify-content-center" style={{ width: '32px', height: '32px', padding: 0 }} onClick={() => handleDelete(book.id, book.title)} title="Delete">
                          <i className="bi bi-trash-fill"></i>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default AdminDashboard;
