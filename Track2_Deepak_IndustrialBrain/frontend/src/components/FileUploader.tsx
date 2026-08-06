import React, { useState, useRef } from 'react';

interface FileUploaderProps {
  onUpload: (file: File) => Promise<void>;
}

export const FileUploader: React.FC<FileUploaderProps> = ({ onUpload }) => {
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") setDragActive(true);
    else if (e.type === "dragleave") setDragActive(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      await processFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      await processFile(e.target.files[0]);
    }
  };

  const processFile = async (file: File) => {
    setUploading(true);
    try {
      await onUpload(file);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div 
      className={`drop-zone ${dragActive ? 'active' : ''}`}
      onDragEnter={handleDrag}
      onDragLeave={handleDrag}
      onDragOver={handleDrag}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      style={{ cursor: uploading ? 'not-allowed' : 'pointer', marginBottom: '2rem' }}
    >
      <input ref={inputRef} type="file" style={{ display: 'none' }} onChange={handleChange} disabled={uploading} />
      {uploading ? (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1rem' }}>
          <div className="spinner" style={{ width: '40px', height: '40px', borderWidth: '3px' }}></div>
          <p style={{ fontWeight: 500 }}>Processing Document...</p>
        </div>
      ) : (
        <div>
          <div style={{ fontSize: '3rem', marginBottom: '1rem', color: 'var(--text-secondary)' }}>⇪</div>
          <h3 style={{ marginBottom: '0.5rem', fontSize: '1.25rem' }}>Drag & drop document here</h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Supports PDF, DOCX, TXT. Up to 50MB.</p>
        </div>
      )}
    </div>
  );
};
