import React, { useState } from 'react';
import {
  Search,
  Sparkles,
  Bot,
  FileText,
  Eye,
  ShieldCheck,
  Tag,
  Calendar,
  Building,
  ChevronRight,
  ArrowRight,
} from 'lucide-react';
import { DocumentItem } from '../types';

interface SemanticSearchViewProps {
  documents: DocumentItem[];
  initialQuery?: string;
  onSelectDocument: (doc: DocumentItem) => void;
}

export const SemanticSearchView: React.FC<SemanticSearchViewProps> = ({
  documents,
  initialQuery = '',
  onSelectDocument,
}) => {
  const [query, setQuery] = useState(initialQuery);
  const [searchResults, setSearchResults] = useState<DocumentItem[]>(documents);
  const [isSearching, setIsSearching] = useState(false);

  const sampleQueries = [
    'Show all Python certificates',
    'Show latest resume',
    'Show internship letters',
    'Show SQL projects',
    'Find AI certifications',
  ];

  const handleSearch = async (q: string) => {
    setQuery(q);
    setIsSearching(true);
    try {
      const res = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q }),
      });
      const data = await res.json();
      if (data.results) {
        setSearchResults(data.results);
      }
    } catch (err) {
      console.error('Search error:', err);
    } finally {
      setIsSearching(false);
    }
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleSearch(query);
  };

  return (
    <div className="p-4 lg:p-8 space-y-6 max-w-5xl mx-auto text-white">
      {/* Header */}
      <div className="border-b border-white/10 pb-6">
        <h1 className="text-2xl font-bold text-white flex items-center space-x-3">
          <Search className="w-6 h-6 text-sky-400" />
          <span>Semantic Vector Search</span>
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Perform natural language vector similarity retrieval over your entire document vault.
        </p>
      </div>

      {/* Main Search Bar & Quick Example Chips */}
      <div className="p-6 rounded-2xl bg-[#0B1F3A]/90 border border-sky-500/30 space-y-4 shadow-xl">
        <form onSubmit={handleFormSubmit} className="relative">
          <Search className="w-5 h-5 text-sky-400 absolute left-4 top-3.5" />
          <input
            type="text"
            placeholder="Ask AI: e.g. 'Show all Python certificates', 'Find Goldman Sachs internship'..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full bg-slate-900 border border-white/10 rounded-xl pl-12 pr-28 py-3 text-sm text-white placeholder-slate-400 focus:outline-none focus:border-sky-400 shadow-inner"
          />
          <button
            type="submit"
            disabled={isSearching}
            className="absolute right-2 top-2 px-5 py-1.5 rounded-lg bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-white text-xs font-semibold shadow-md shadow-sky-500/20"
          >
            {isSearching ? 'Searching...' : 'Vector Search'}
          </button>
        </form>

        {/* Quick Suggestion Chips */}
        <div className="space-y-2">
          <div className="text-[10px] text-slate-400 font-mono uppercase tracking-wider flex items-center space-x-1">
            <Sparkles className="w-3 h-3 text-sky-400" />
            <span>Suggested Vector Queries:</span>
          </div>

          <div className="flex flex-wrap gap-2">
            {sampleQueries.map((sample, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => handleSearch(sample)}
                className="px-3 py-1.5 rounded-xl bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/30 text-sky-300 text-xs font-medium transition-all flex items-center space-x-1"
              >
                <span>{sample}</span>
                <ArrowRight className="w-3 h-3 text-sky-400" />
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Results Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between text-xs text-slate-400 font-mono px-1">
          <span>Search Results ({searchResults.length})</span>
          {query && <span className="text-sky-400">Ranked by Vector Similarity</span>}
        </div>

        <div className="space-y-4">
          {searchResults.map((doc) => {
            const matchScore = doc.embeddingVectorSim
              ? Math.round(doc.embeddingVectorSim * 100)
              : 88;

            return (
              <div
                key={doc.id}
                className="p-5 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 hover:border-sky-500/40 transition-all backdrop-blur-md flex flex-col md:flex-row md:items-center justify-between gap-4 group"
              >
                <div className="space-y-2 flex-1">
                  <div className="flex items-center space-x-2">
                    <span className="px-2.5 py-0.5 rounded bg-sky-500/15 text-sky-300 font-mono text-[10px] font-bold uppercase">
                      {doc.category}
                    </span>
                    <span className="text-xs text-slate-400 font-mono">{doc.organization}</span>
                    <span className="text-xs text-emerald-400 font-mono font-bold ml-auto sm:ml-0">
                      {matchScore}% Match Score
                    </span>
                  </div>

                  <h3
                    onClick={() => onSelectDocument(doc)}
                    className="text-base font-bold text-white group-hover:text-sky-300 transition-colors cursor-pointer"
                  >
                    {doc.title}
                  </h3>

                  <p className="text-xs text-slate-300 leading-relaxed">{doc.summary}</p>

                  <div className="flex flex-wrap gap-1 pt-1">
                    {doc.skills.map((s, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="shrink-0 flex items-center space-x-2 border-t md:border-t-0 md:border-l border-white/10 pt-3 md:pt-0 md:pl-4">
                  <button
                    onClick={() => onSelectDocument(doc)}
                    className="px-4 py-2 rounded-xl bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 text-xs font-semibold flex items-center space-x-1.5"
                  >
                    <Eye className="w-3.5 h-3.5" />
                    <span>View Detail</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
