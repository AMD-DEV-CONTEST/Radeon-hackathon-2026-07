import React, { useState } from 'react';
import {
  X,
  Upload,
  FileText,
  Sparkles,
  CheckCircle2,
  Bot,
  AlertCircle,
  File,
} from 'lucide-react';
import { DocumentCategory, DocumentItem } from '../types';

interface UploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUploadSuccess: (doc: DocumentItem) => void;
}

export const UploadModal: React.FC<UploadModalProps> = ({
  isOpen,
  onClose,
  onUploadSuccess,
}) => {
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState<DocumentCategory>('Certificates');
  const [organization, setOrganization] = useState('');
  const [rawText, setRawText] = useState('');
  const [fileName, setFileName] = useState('');
  const [fileType, setFileType] = useState<'pdf' | 'docx' | 'image' | 'zip'>('pdf');
  const [uploadStep, setUploadStep] = useState<number>(0); // 0: Form, 1: Uploading/OCR, 2: NLP/Embeddings, 3: Complete
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const categories: DocumentCategory[] = [
    'Projects',
    'Certificates',
    'Internships',
    'Achievements',
    'Research',
    'Hackathons',
    'Academics',
    'Skills',
    'Resume',
  ];

  const handleFileDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      setFileName(file.name);
      if (!title) {
        const cleanName = file.name.replace(/\.[^/.]+$/, '').replace(/_/g, ' ');
        setTitle(cleanName.charAt(0).toUpperCase() + cleanName.slice(1));
      }
      const ext = file.name.split('.').pop()?.toLowerCase();
      if (ext === 'docx') setFileType('docx');
      else if (['png', 'jpg', 'jpeg'].includes(ext || '')) setFileType('image');
      else if (ext === 'zip') setFileType('zip');
      else setFileType('pdf');
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      setFileName(file.name);
      if (!title) {
        const cleanName = file.name.replace(/\.[^/.]+$/, '').replace(/_/g, ' ');
        setTitle(cleanName.charAt(0).toUpperCase() + cleanName.slice(1));
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title) {
      setError('Document title is required');
      return;
    }

    setError('');
    setUploadStep(1); // Step 1: OCR Extraction

    try {
      setTimeout(async () => {
        setUploadStep(2); // Step 2: NLP & Embeddings

        setTimeout(async () => {
          const res = await fetch('/api/documents/upload', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              title,
              fileName: fileName || `${title.replace(/\s+/g, '_')}.${fileType}`,
              fileType,
              category,
              organization: organization || 'Stanford University',
              rawText:
                rawText ||
                `Document Title: ${title}. Category: ${category}. Organization: ${organization}. Contains verified achievement metrics and key technical skill competencies.`,
            }),
          });

          const data = await res.json();
          setUploadStep(3); // Complete

          setTimeout(() => {
            if (data.document) {
              onUploadSuccess(data.document);
            }
            onClose();
            setUploadStep(0);
            setTitle('');
            setOrganization('');
            setRawText('');
            setFileName('');
          }, 1000);
        }, 1200);
      }, 1000);
    } catch (err: any) {
      setError(err?.message || 'Upload failed');
      setUploadStep(0);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
      <div className="bg-[#0B1F3A] border border-sky-500/30 rounded-2xl w-full max-w-xl p-6 sm:p-8 text-white shadow-2xl relative overflow-hidden">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-white p-2 rounded-lg bg-white/5 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Title */}
        <div className="flex items-center space-x-3 mb-6">
          <div className="p-3 rounded-xl bg-sky-500/10 border border-sky-500/30 text-sky-400">
            <Upload className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">Upload to MyAI Vault</h2>
            <p className="text-xs text-slate-400">PDF, DOCX, Images, or ZIP • AI Pipeline Processing</p>
          </div>
        </div>

        {/* Pipeline Progress View */}
        {uploadStep > 0 ? (
          <div className="py-8 space-y-6 text-center">
            <div className="w-16 h-16 rounded-2xl bg-sky-500/20 text-sky-400 flex items-center justify-center mx-auto border border-sky-500/40 animate-pulse">
              <Bot className="w-8 h-8" />
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-bold text-white">
                {uploadStep === 1
                  ? '1. OCR & Text Extraction...'
                  : uploadStep === 2
                  ? '2. NLP Skill Tagging & Vector Embeddings...'
                  : '3. Identity Vault Indexing Complete!'}
              </h3>
              <p className="text-xs text-slate-300 max-w-sm mx-auto">
                Gemini AI is parsing document text, mapping knowledge links, and updating your ATS career profile.
              </p>
            </div>

            {/* Step Indicators */}
            <div className="flex items-center justify-center space-x-4 pt-2 text-xs">
              <div
                className={`flex items-center space-x-1 ${
                  uploadStep >= 1 ? 'text-sky-400 font-bold' : 'text-slate-600'
                }`}
              >
                <CheckCircle2 className="w-4 h-4" />
                <span>OCR</span>
              </div>
              <span className="text-slate-700">→</span>
              <div
                className={`flex items-center space-x-1 ${
                  uploadStep >= 2 ? 'text-sky-400 font-bold' : 'text-slate-600'
                }`}
              >
                <CheckCircle2 className="w-4 h-4" />
                <span>Embeddings</span>
              </div>
              <span className="text-slate-700">→</span>
              <div
                className={`flex items-center space-x-1 ${
                  uploadStep >= 3 ? 'text-emerald-400 font-bold' : 'text-slate-600'
                }`}
              >
                <CheckCircle2 className="w-4 h-4" />
                <span>Indexed</span>
              </div>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Drag & Drop Box */}
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleFileDrop}
              className="p-6 rounded-2xl bg-slate-900/80 border-2 border-dashed border-sky-500/30 hover:border-sky-400 transition-colors text-center space-y-2 relative"
            >
              <input
                type="file"
                accept=".pdf,.docx,.png,.jpg,.jpeg,.zip"
                onChange={handleFileChange}
                className="absolute inset-0 opacity-0 cursor-pointer"
              />
              <Upload className="w-8 h-8 text-sky-400 mx-auto" />
              <div className="text-xs font-semibold text-white">
                {fileName ? (
                  <span className="text-sky-300 font-mono">Selected: {fileName}</span>
                ) : (
                  <span>Drag & Drop PDF, DOCX, Image, or ZIP here</span>
                )}
              </div>
              <p className="text-[10px] text-slate-400">or click to browse files from your computer</p>
            </div>

            {error && <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">{error}</div>}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div>
                <label className="block text-slate-300 font-medium mb-1">Document Title *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Stanford Deep Learning Certificate"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="w-full bg-slate-900 border border-white/10 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-sky-400"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-medium mb-1">Category</label>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value as DocumentCategory)}
                  className="w-full bg-slate-900 border border-white/10 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-sky-400"
                >
                  {categories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>

              <div className="sm:col-span-2">
                <label className="block text-slate-300 font-medium mb-1">Issuing Organization / Institution</label>
                <input
                  type="text"
                  placeholder="e.g. Stanford Online, Goldman Sachs, AWS"
                  value={organization}
                  onChange={(e) => setOrganization(e.target.value)}
                  className="w-full bg-slate-900 border border-white/10 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-sky-400"
                />
              </div>

              <div className="sm:col-span-2">
                <label className="block text-slate-300 font-medium mb-1">
                  Optional Key Excerpt / Text Content
                </label>
                <textarea
                  rows={2}
                  placeholder="Paste certificate or project text excerpt for AI processing..."
                  value={rawText}
                  onChange={(e) => setRawText(e.target.value)}
                  className="w-full bg-slate-900 border border-white/10 rounded-xl p-3 text-xs text-white focus:outline-none focus:border-sky-400"
                />
              </div>
            </div>

            <div className="flex justify-end space-x-3 pt-3 border-t border-white/10">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2.5 rounded-xl text-slate-300 hover:text-white text-xs font-medium"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-white font-semibold text-xs shadow-lg shadow-sky-500/20"
              >
                Run AI Pipeline & Index
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
