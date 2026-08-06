import React from 'react';
import { Link } from 'react-router-dom';

const RecommendationCard = ({ book }) => {
  const { id, title, author, category, shelfNumber, availability, imageUrl } = book;
  const coverImage = imageUrl || `https://images.unsplash.com/photo-1543002588-bfa74002ed7e?q=80&w=300`;

  return (
    <div className="card glass-card reco-card border-0 h-100 hover-scale" style={{ maxWidth: '240px' }}>
      <div style={{ height: '140px', overflow: 'hidden' }}>
        <img 
          src={coverImage} 
          className="card-img-top h-100 w-100 object-fit-cover" 
          alt={title}
          onError={(e) => {
            e.target.src = `https://images.unsplash.com/photo-1543002588-bfa74002ed7e?q=80&w=300`;
          }}
        />
      </div>
      <div className="card-body p-3 d-flex flex-column">
        <span className="badge bg-secondary text-white rounded-pill px-2 py-0.5 mb-2 align-self-start" style={{ fontSize: '0.75rem' }}>
          {category}
        </span>
        <h6 className="card-title fw-bold text-truncate mb-1" title={title} style={{ fontSize: '0.9rem' }}>{title}</h6>
        <p className="text-muted mb-2 text-truncate" style={{ fontSize: '0.8rem' }}>{author}</p>
        
        <div className="mt-auto d-flex align-items-center justify-content-between pt-2 border-top border-secondary border-opacity-10" style={{ fontSize: '0.75rem' }}>
          <span className="text-muted"><i className="bi bi-geo-alt-fill text-info me-1"></i>Shelf <strong>{shelfNumber}</strong></span>
          <Link to={`/books/${id}`} className="btn btn-xs btn-primary rounded-pill py-1 px-2" style={{ fontSize: '0.75rem' }}>
            Open
          </Link>
        </div>
      </div>
    </div>
  );
};

export default RecommendationCard;
