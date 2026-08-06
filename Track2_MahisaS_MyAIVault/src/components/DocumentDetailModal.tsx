import React from 'react';
import {
  X,
  FileText,
  Award,
  Briefcase,
  CheckCircle2,
  Download,
  Trash2,
  Sparkles,
  Tag,
  Calendar,
  Building,
  ShieldCheck,
  ExternalLink,
} from 'lucide-react';
import { DocumentItem } from '../types';

interface DocumentDetailModalProps {
  document: DocumentItem | null;
  onClose: () => void;
  onDelete: (docId: string) => void;
}

export const DocumentDetailModal: React.FC<DocumentDetailModalProps> = ({
  document,
  onClose,
  onDelete,
}) => {
  if (!document) return null;

  const handleDownload = () => {
    const element = document.createElement('a');
    const file = new Blob([document.extractedText], { type: 'text/plain' });
    element.href = URL.createObjectURL(file);
    element.download = `${document.title.replace(/\s+/g, '_')}_Transcript.txt`;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4 overflow-y-auto">
      <div className="bg-[#0B1F3A] border border-sky-500/30 rounded-2xl w-full max-w-3xl p-6 sm:p-8 text-white shadow-2xl relative my-8">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-white p-2 rounded-lg bg-white/5 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Modal Header */}
        <div className="flex items-start space-x-4 mb-6 border-b border-white/10 pb-5">
          <div className="p-3.5 rounded-2xl bg-sky-500/10 border border-sky-500/30 text-sky-400 shrink-0">
            <FileText className="w-7 h-7" />
          </div>
          <div className="pr-8">
            <div className="flex items-center space-x-2 mb-1">
              <span className="px-2.5 py-0.5 rounded bg-sky-500/20 text-sky-300 font-mono text-[10px] uppercase font-bold tracking-wider">
                {document.category}
              </span>
              <span className="text-xs text-emerald-400 font-mono flex items-center space-x-1">
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>Verified in AI Vault</span>
              </span>
            </div>
            <h2 className="text-xl font-bold text-white">{document.title}</h2>
            <p className="text-xs text-slate-400 font-mono mt-0.5">
              File: {document.fileName} • {document.fileSize}
            </p>
          </div>
        </div>

        {/* Details Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          {/* Metadata Info Box */}
          <div className="p-4 rounded-xl bg-slate-900/80 border border-white/10 space-y-3">
            <h3 className="text-xs font-bold text-sky-300 uppercase font-mono tracking-wider">
              Document Metadata
            </h3>

            <div className="space-y-2 text-xs">
              <div className="flex items-center justify-between text-slate-300">
                <span className="text-slate-400 flex items-center space-x-1.5">
                  <Building className="w-3.5 h-3.5 text-sky-400" />
                  <span>Issuing Org:</span>
                </span>
                <strong className="text-white">{document.organization}</strong>
              </div>

              <div className="flex items-center justify-between text-slate-300">
                <span className="text-slate-400 flex items-center space-x-1.5">
                  <Calendar className="w-3.5 h-3.5 text-sky-400" />
                  <span>Issue Date:</span>
                </span>
                <strong className="text-white font-mono">{document.issueDate}</strong>
              </div>

              <div className="flex items-center justify-between text-slate-300">
                <span className="text-slate-400 flex items-center space-x-1.5">
                  <Tag className="w-3.5 h-3.5 text-sky-400" />
                  <span>Category:</span>
                </span>
                <strong className="text-white">{document.category}</strong>
              </div>
            </div>
          </div>

          {/* AI Extracted Skills */}
          <div className="p-4 rounded-xl bg-slate-900/80 border border-white/10 space-y-3">
            <h3 className="text-xs font-bold text-sky-300 uppercase font-mono tracking-wider flex items-center space-x-1">
              <Sparkles className="w-3.5 h-3.5" />
              <span>Extracted Technical Skills</span>
            </h3>

            <div className="flex flex-wrap gap-1.5">
              {document.skills.map((skill, idx) => (
                <span
                  key={idx}
                  className="px-2.5 py-1 rounded-lg bg-sky-500/15 border border-sky-500/30 text-sky-200 text-xs font-medium"
                >
                  {skill}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* AI Summary */}
        <div className="p-4 rounded-xl bg-slate-900/80 border border-white/10 space-y-2 mb-6">
          <h3 className="text-xs font-bold text-sky-300 uppercase font-mono tracking-wider flex items-center space-x-1.5">
            <Sparkles className="w-3.5 h-3.5 text-sky-400" />
            <span>AI Executive Summary</span>
          </h3>
          <p className="text-xs text-slate-200 leading-relaxed">{document.summary}</p>
        </div>

        {/* Styled Document Content Viewer */}
        <div className="p-4 rounded-xl bg-slate-950 border border-white/10 space-y-2 mb-6 max-h-48 overflow-y-auto font-mono text-xs text-slate-300">
          <div className="text-[10px] text-slate-500 uppercase tracking-widest border-b border-white/10 pb-1 mb-2">
            OCR Extracted Text View
          </div>
          <p className="leading-relaxed whitespace-pre-line">{document.extractedText}</p>
        </div>

        {/* Bottom Actions */}
        <div className="flex items-center justify-between border-t border-white/10 pt-5">
          <button
            onClick={() => {
              onDelete(document.id);
              onClose();
            }}
            className="px-4 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-400 text-xs font-semibold flex items-center space-x-2 border border-red-500/20 transition-colors"
          >
            <Trash2 className="w-4 h-4" />
            <span>Delete Document</span>
          </button>

          <div className="flex items-center space-x-3">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-slate-300 hover:text-white text-xs font-medium"
            >
              Close
            </button>
            <button
              onClick={handleDownload}
              className="px-5 py-2 rounded-xl bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-white text-xs font-semibold flex items-center space-x-2 shadow-md shadow-sky-500/20"
            >
              <Download className="w-4 h-4" />
              <span>Download Transcript</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
