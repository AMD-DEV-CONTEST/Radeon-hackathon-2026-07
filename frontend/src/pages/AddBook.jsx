import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { bookService } from '../services/api';

const AddBook = () => {
  const navigate = useNavigate();
  const [formData, setFormData] = useState({
    title: '',
    author: '',
    category: '',
    description: '',
    publisher: '',
    isbn: '',
    shelfNumber: '',
    quantity: 1,
    imageUrl: ''
  });
  
  const [categories, setCategories] = useState([]);
  const [customCategory, setCustomCategory] = useState('');
  const [showCustomCat, setShowCustomCat] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState({});
  const [toast, setToast] = useState(null);

  // Auth Guard
  useEffect(() => {
    const isAdmin = localStorage.getItem('isAdmin') === 'true';
    if (!isAdmin) {
      navigate('/admin-login');
    }
  }, [navigate]);

  useEffect(() => {
    const fetchCats = async () => {
      try {
        const cats = await bookService.getCategories();
        setCategories(cats);
      } catch (err) {
        console.error(err);
      }
    };
    fetchCats();
  }, []);

  const showToast = (type, message) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 4000);
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    // Clear validation error on change
    if (errors[name]) {
      setErrors((prev) => ({ ...prev, [name]: '' }));
    }
  };

  const validate = () => {
    const newErrors = {};
    if (!formData.title.trim()) newErrors.title = 'Book title is required';
    if (!formData.author.trim()) newErrors.author = 'Author name is required';
    
    const finalCategory = showCustomCat ? customCategory : formData.category;
    if (!finalCategory || !finalCategory.trim()) {
      newErrors.category = 'Category selection is required';
    }

    if (formData.quantity === null || formData.quantity === undefined || formData.quantity < 0) {
      newErrors.quantity = 'Quantity must be 0 or more';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!validate()) return;

    setLoading(true);
    const finalCategory = showCustomCat ? customCategory : formData.category;
    const submissionData = { ...formData, category: finalCategory };

    try {
      await bookService.createBook(submissionData);
      showToast('success', 'Book added successfully!');
      setTimeout(() => navigate('/admin'), 1000);
    } catch (err) {
      console.error(err);
      if (err.response?.data?.validationErrors) {
        setErrors(err.response.data.validationErrors);
      } else {
        showToast('error', 'Failed to save book. Verify database connectivity.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container py-5 fade-in">
      {/* Toast Alert */}
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

      <div className="mb-4">
        <Link to="/admin" className="text-decoration-none text-muted">
          <i className="bi bi-arrow-left me-1"></i> Back to Dashboard
        </Link>
      </div>

      <div className="row justify-content-center">
        <div className="col-lg-8">
          <div className="card glass-card border-0 p-4 p-md-5 rounded-4 shadow-sm">
            <h2 className="fw-extrabold heading-font mb-4">Add New Book</h2>

            <form onSubmit={handleSubmit}>
              <div className="row g-3">
                
                {/* Title */}
                <div className="col-12">
                  <label className="form-label text-muted small">Book Title *</label>
                  <input 
                    type="text" 
                    name="title"
                    className={`form-control ${errors.title ? 'is-invalid' : ''}`}
                    placeholder="e.g., Designing Data-Intensive Applications"
                    value={formData.title}
                    onChange={handleChange}
                  />
                  {errors.title && <div className="invalid-feedback">{errors.title}</div>}
                </div>

                {/* Author */}
                <div className="col-md-6">
                  <label className="form-label text-muted small">Author *</label>
                  <input 
                    type="text" 
                    name="author"
                    className={`form-control ${errors.author ? 'is-invalid' : ''}`}
                    placeholder="e.g., Martin Kleppmann"
                    value={formData.author}
                    onChange={handleChange}
                  />
                  {errors.author && <div className="invalid-feedback">{errors.author}</div>}
                </div>

                {/* Category Selection */}
                <div className="col-md-6">
                  <label className="form-label text-muted small">Category *</label>
                  {!showCustomCat ? (
                    <div className="input-group">
                      <select 
                        name="category"
                        className={`form-select ${errors.category ? 'is-invalid' : ''}`}
                        value={formData.category}
                        onChange={handleChange}
                      >
                        <option value="">Select Category</option>
                        {categories.map((cat, idx) => (
                          <option key={idx} value={cat}>{cat}</option>
                        ))}
                      </select>
                      <button 
                        type="button" 
                        className="btn btn-outline-secondary" 
                        onClick={() => setShowCustomCat(true)}
                        title="Add custom category"
                      >
                        New
                      </button>
                      {errors.category && <div className="invalid-feedback">{errors.category}</div>}
                    </div>
                  ) : (
                    <div className="input-group">
                      <input 
                        type="text" 
                        className={`form-control ${errors.category ? 'is-invalid' : ''}`}
                        placeholder="Enter custom category"
                        value={customCategory}
                        onChange={(e) => setCustomCategory(e.target.value)}
                      />
                      <button 
                        type="button" 
                        className="btn btn-outline-secondary" 
                        onClick={() => { setShowCustomCat(false); setCustomCategory(''); }}
                      >
                        Cancel
                      </button>
                      {errors.category && <div className="invalid-feedback">{errors.category}</div>}
                    </div>
                  )}
                </div>

                {/* Publisher */}
                <div className="col-md-6">
                  <label className="form-label text-muted small">Publisher</label>
                  <input 
                    type="text" 
                    name="publisher"
                    className="form-control"
                    placeholder="e.g., O'Reilly"
                    value={formData.publisher}
                    onChange={handleChange}
                  />
                </div>

                {/* ISBN */}
                <div className="col-md-6">
                  <label className="form-label text-muted small">ISBN</label>
                  <input 
                    type="text" 
                    name="isbn"
                    className={`form-control ${errors.isbn ? 'is-invalid' : ''}`}
                    placeholder="e.g., 978-1449373320"
                    value={formData.isbn}
                    onChange={handleChange}
                  />
                  {errors.isbn && <div className="invalid-feedback">{errors.isbn}</div>}
                </div>

                {/* Shelf Number */}
                <div className="col-md-6">
                  <label className="form-label text-muted small">Shelf Number (Zone-Block)</label>
                  <input 
                    type="text" 
                    name="shelfNumber"
                    className="form-control"
                    placeholder="e.g., DB-301 (Letters match Zone Grid)"
                    value={formData.shelfNumber}
                    onChange={handleChange}
                  />
                </div>

                {/* Quantity */}
                <div className="col-md-6">
                  <label className="form-label text-muted small">Quantity In Stock *</label>
                  <input 
                    type="number" 
                    name="quantity"
                    min="0"
                    className={`form-control ${errors.quantity ? 'is-invalid' : ''}`}
                    value={formData.quantity}
                    onChange={handleChange}
                  />
                  {errors.quantity && <div className="invalid-feedback">{errors.quantity}</div>}
                </div>

                {/* Cover Image URL */}
                <div className="col-12">
                  <label className="form-label text-muted small">Cover Image URL</label>
                  <input 
                    type="text" 
                    name="imageUrl"
                    className="form-control"
                    placeholder="e.g., https://images.unsplash.com/photo-1544383835-bda2bc66a55d"
                    value={formData.imageUrl}
                    onChange={handleChange}
                  />
                  {formData.imageUrl && (
                    <div className="mt-3">
                      <small className="text-muted d-block mb-1">Image Preview:</small>
                      <img 
                        src={formData.imageUrl} 
                        alt="Preview" 
                        className="rounded"
                        style={{ height: '120px', width: '90px', objectFit: 'cover' }}
                        onError={(e) => e.target.style.display = 'none'}
                      />
                    </div>
                  )}
                </div>

                {/* Description */}
                <div className="col-12">
                  <label className="form-label text-muted small">Description</label>
                  <textarea 
                    name="description"
                    className="form-control"
                    rows="4"
                    placeholder="Add brief description/synopsis of the book..."
                    value={formData.description}
                    onChange={handleChange}
                  ></textarea>
                </div>

              </div>

              <div className="d-flex justify-content-end gap-3 mt-4 pt-4 border-top border-secondary border-opacity-10">
                <Link to="/admin" className="btn btn-outline-secondary rounded-pill px-4">
                  Cancel
                </Link>
                <button type="submit" className="btn btn-primary rounded-pill px-4" disabled={loading}>
                  {loading ? 'Saving...' : 'Add Book'}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AddBook;
