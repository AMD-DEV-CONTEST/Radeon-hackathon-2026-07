import React from 'react';
import { Link } from 'react-router-dom';

const BookCard = ({ book }) => {
  const { id, title, author, category, shelfNumber, quantity, availability, imageUrl } = book;
  const coverImage = imageUrl || `https://images.unsplash.com/photo-1543002588-bfa74002ed7e?q=80&w=300`;

  return (
    <div className="card glass-card h-100 border-0 overflow-hidden fade-in book-card">
      <div className="position-relative" style={{ height: '220px', overflow: 'hidden' }}>
        <img
          src={coverImage}
          alt={title}
          className="w-100 h-100 object-fit-cover"
          onError={(e) => {
            e.target.src = `https://images.unsplash.com/photo-1543002588-bfa74002ed7e?q=80&w=300`;
          }}
        />
        <div className="position-absolute top-0 end-0 m-3">
          <span className={`badge rounded-pill px-3 py-2 ${availability ? 'bg-success' : 'bg-danger'}`}>
            {availability ? `${quantity} available` : 'Out of stock'}
          </span>
        </div>
        <div className="position-absolute bottom-0 start-0 m-3">
          <span className="badge rounded-pill px-3 py-1" style={{ background: 'rgba(31, 111, 102, 0.9)', color: '#fff' }}>
            {category}
          </span>
        </div>
      </div>

      <div className="card-body d-flex flex-column p-4">
        <h5 className="card-title fw-bold mb-1" title={title}>{title}</h5>
        <p className="text-muted mb-3" style={{ fontSize: '0.92rem' }}>by {author}</p>

        <div className="mt-auto d-flex justify-content-between align-items-center">
          <div className="d-flex align-items-center text-muted gap-1" style={{ fontSize: '0.86rem' }}>
            <i className="bi bi-geo-alt-fill" style={{ color: 'var(--primary-color)' }}></i>
            <span>Shelf <strong>{shelfNumber}</strong></span>
          </div>
          <Link to={`/books/${id}`} className="btn btn-sm btn-primary rounded-pill px-3">
            View Details
          </Link>
        </div>
      </div>
    </div>
  );
};

export default BookCard;
