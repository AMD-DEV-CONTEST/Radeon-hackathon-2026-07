import React, { useState } from 'react';
import {
  FileText,
  Upload,
  Search,
  Grid,
  List,
  Eye,
  Trash2,
  Download,
  Filter,
  Sparkles,
  Bot,
  Plus,
  ShieldCheck,
  CheckCircle2,
  X,
  ExternalLink,
  Tag,
} from 'lucide-react';
import { DocumentItem, DocumentCategory } from '../types';

interface DocumentsViewProps {
  documents: DocumentItem[];
  selectedCategory: string;
  onSelectCategory: (category: string) => void;
  onOpenUpload: () => void;
  onSelectDocument: (doc: DocumentItem) => void;
  onDeleteDocument: (docId: string) => void;
  onAddSampleDoc: (type: 'cert' | 'resume' | 'project') => void;
}

export const DocumentsView: React.FC<DocumentsViewProps> = ({
  documents,
  selectedCategory,
  onSelectCategory,
  onOpenUpload,
  onSelectDocument,
  onDeleteDocument,
  onAddSampleDoc,
}) => {
  const [viewMode, setViewMode] = useState<'grid' | 'table'>('grid');
  const [filterQuery, setFilterQuery] = useState('');

  const categories: string[] = [
    'All',
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

  const filteredDocs = documents.filter((doc) => {
    const matchesCategory = selectedCategory === 'All' || doc.category === selectedCategory;
    const q = filterQuery.toLowerCase();
    const matchesSearch =
      !q ||
      doc.title.toLowerCase().includes(q) ||
      doc.organization.toLowerCase().includes(q) ||
      doc.skills.some((s) => s.toLowerCase().includes(q));
    return matchesCategory && matchesSearch;
  });

  return (
    <div className="p-4 lg:p-8 space-y-6 max-w-7xl mx-auto text-white">
      {/* Top Header & Actions */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/10 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center space-x-3">
            <FileText className="w-6 h-6 text-sky-400" />
            <span>Documents Vault</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Centralized AI digital memory storing verified certificates, projects, and career credentials.
          </p>
        </div>

        <div className="flex items-center space-x-3">
          {/* Quick Add Sample Buttons */}
          <div className="hidden sm:flex items-center space-x-2">
            <button
              onClick={() => onAddSampleDoc('cert')}
              className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-sky-300 border border-sky-500/20 flex items-center space-x-1"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>+ Sample Cert</span>
            </button>
            <button
              onClick={() => onAddSampleDoc('project')}
              className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-indigo-300 border border-indigo-500/20 flex items-center space-x-1"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>+ Sample Project</span>
            </button>
          </div>

          <button
            onClick={onOpenUpload}
            className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-white font-semibold text-xs shadow-lg shadow-sky-500/20 flex items-center space-x-2 transition-all transform hover:-translate-y-0.5"
          >
            <Upload className="w-4 h-4" />
            <span>Upload New Document</span>
          </button>
        </div>
      </div>

      {/* Category Pills & Filters */}
      <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-4">
        {/* Scrollable Pills */}
        <div className="flex items-center space-x-2 overflow-x-auto pb-2 lg:pb-0 no-scrollbar">
          {categories.map((cat) => {
            const isSelected = selectedCategory === cat;
            return (
              <button
                key={cat}
                onClick={() => onSelectCategory(cat)}
                className={`px-3.5 py-1.5 rounded-xl text-xs font-medium whitespace-nowrap transition-all ${
                  isSelected
                    ? 'bg-sky-500 text-slate-950 font-bold shadow-md shadow-sky-500/20'
                    : 'bg-slate-900/80 text-slate-300 hover:text-white border border-white/10 hover:border-sky-500/30'
                }`}
              >
                {cat}
              </button>
            );
          })}
        </div>

        {/* Filter Input & Layout Switcher */}
        <div className="flex items-center space-x-3">
          <div className="relative flex-1 lg:w-64">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-2.5" />
            <input
              type="text"
              placeholder="Filter by title or skill..."
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              className="w-full bg-slate-900/80 border border-white/10 rounded-xl pl-9 pr-3 py-1.5 text-xs text-white placeholder-slate-400 focus:outline-none focus:border-sky-400"
            />
          </div>

          <div className="flex items-center p-1 bg-slate-900/80 border border-white/10 rounded-xl">
            <button
              onClick={() => setViewMode('grid')}
              className={`p-1.5 rounded-lg text-xs ${viewMode === 'grid' ? 'bg-sky-500 text-slate-950 font-bold' : 'text-slate-400 hover:text-white'}`}
            >
              <Grid className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setViewMode('table')}
              className={`p-1.5 rounded-lg text-xs ${viewMode === 'table' ? 'bg-sky-500 text-slate-950 font-bold' : 'text-slate-400 hover:text-white'}`}
            >
              <List className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Grid or Table Display */}
      {filteredDocs.length === 0 ? (
        <div className="p-12 text-center bg-[#0B1F3A]/40 border border-white/10 rounded-2xl space-y-3">
          <FileText className="w-10 h-10 text-slate-500 mx-auto" />
          <h3 className="text-base font-bold text-white">No documents found</h3>
          <p className="text-xs text-slate-400 max-w-sm mx-auto">
            Try adjusting your search filters or click "Upload New Document" to add your credentials.
          </p>
          <button
            onClick={onOpenUpload}
            className="px-4 py-2 rounded-xl bg-sky-500/20 text-sky-300 text-xs font-semibold border border-sky-500/30"
          >
            Upload Document Now
          </button>
        </div>
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredDocs.map((doc) => (
            <div
              key={doc.id}
              className="p-5 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 hover:border-sky-500/40 transition-all backdrop-blur-md flex flex-col justify-between space-y-4 group"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="px-2.5 py-0.5 rounded-md bg-sky-500/15 text-sky-300 font-mono text-[10px] font-semibold uppercase tracking-wider">
                    {doc.category}
                  </span>
                  <span className="text-[10px] text-slate-400 font-mono">{doc.issueDate}</span>
                </div>

                <h3
                  onClick={() => onSelectDocument(doc)}
                  className="text-base font-bold text-white group-hover:text-sky-300 transition-colors cursor-pointer line-clamp-1"
                >
                  {doc.title}
                </h3>

                <p className="text-xs text-slate-400 font-medium">{doc.organization}</p>

                <p className="text-xs text-slate-300 leading-relaxed line-clamp-2">{doc.summary}</p>
              </div>

              <div className="space-y-3 pt-3 border-t border-white/10">
                <div className="flex flex-wrap gap-1">
                  {doc.skills.map((skill, idx) => (
                    <span
                      key={idx}
                      className="px-2 py-0.5 rounded bg-slate-800/80 border border-white/5 text-[10px] text-slate-300"
                    >
                      {skill}
                    </span>
                  ))}
                </div>

                <div className="flex items-center justify-between pt-1 text-xs">
                  <span className="text-[10px] text-emerald-400 font-mono flex items-center space-x-1">
                    <ShieldCheck className="w-3 h-3" />
                    <span>AI Verified</span>
                  </span>

                  <div className="flex items-center space-x-1">
                    <button
                      onClick={() => onSelectDocument(doc)}
                      className="p-1.5 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-400"
                      title="View Details"
                    >
                      <Eye className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => onDeleteDocument(doc.id)}
                      className="p-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400"
                      title="Delete Document"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="p-6 rounded-2xl bg-[#0B1F3A]/80 border border-white/10 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-slate-400 font-mono border-b border-white/10 uppercase text-[10px]">
                <th className="py-3 px-3">Title & File</th>
                <th className="py-3 px-3">Category</th>
                <th className="py-3 px-3">Issuer / Org</th>
                <th className="py-3 px-3">Summary</th>
                <th className="py-3 px-3">Extracted Skills</th>
                <th className="py-3 px-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {filteredDocs.map((doc) => (
                <tr key={doc.id} className="hover:bg-white/5 transition-colors">
                  <td className="py-3 px-3">
                    <strong
                      onClick={() => onSelectDocument(doc)}
                      className="text-white block font-semibold hover:text-sky-300 cursor-pointer"
                    >
                      {doc.title}
                    </strong>
                    <span className="text-[10px] text-slate-400 font-mono">{doc.fileName}</span>
                  </td>
                  <td className="py-3 px-3">
                    <span className="px-2 py-0.5 rounded bg-sky-500/15 text-sky-300 font-mono text-[10px]">
                      {doc.category}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-slate-300">{doc.organization}</td>
                  <td className="py-3 px-3 text-slate-300 max-w-xs truncate">{doc.summary}</td>
                  <td className="py-3 px-3">
                    <div className="flex flex-wrap gap-1 max-w-xs">
                      {doc.skills.map((s, idx) => (
                        <span key={idx} className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">
                          {s}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="py-3 px-3 text-right space-x-2">
                    <button
                      onClick={() => onSelectDocument(doc)}
                      className="p-1.5 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-400"
                    >
                      <Eye className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => onDeleteDocument(doc.id)}
                      className="p-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
