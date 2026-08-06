import React, { useState } from 'react';
import { DocumentRecord } from '../types';

interface DocumentTableProps {
  documents: DocumentRecord[];
  onDelete: (id: string) => void;
}

export const DocumentTable: React.FC<DocumentTableProps> = ({ documents, onDelete }) => {
  const [search, setSearch] = useState('');

  const filtered = documents.filter(d => d.filename.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="card" style={{ padding: '0' }}>
      <div style={{ padding: '1.5rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ fontSize: '1.2rem', fontWeight: 600 }}>Document Repository</h3>
        <input 
          type="text" 
          className="input" 
          placeholder="Search files..." 
          value={search} 
          onChange={e => setSearch(e.target.value)}
          style={{ width: '250px', padding: '0.5rem 1rem' }}
        />
      </div>
      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              <th>Filename</th>
              <th>Status</th>
              <th>Upload Date</th>
              <th>Size (KB)</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(doc => (
              <tr key={doc.id}>
                <td style={{ fontWeight: 500 }}>{doc.filename}</td>
                <td>
                  <span className={`badge badge-${doc.status === 'ready' ? 'success' : doc.status === 'failed' ? 'danger' : 'warning'}`}>
                    {doc.status.toUpperCase()}
                  </span>
                </td>
                <td>{new Date(doc.uploadDate).toLocaleDateString()}</td>
                <td>{Math.round(doc.size / 1024)}</td>
                <td style={{ textAlign: 'right' }}>
                  <button className="btn btn-danger" style={{ padding: '0.25rem 0.5rem', fontSize: '0.8rem' }} onClick={() => onDelete(doc.id)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={5} style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                  No documents found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
