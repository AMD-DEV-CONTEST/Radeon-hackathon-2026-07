import React, { useState } from 'react';
import {
  Clock,
  Award,
  Briefcase,
  FileText,
  Code,
  GraduationCap,
  Sparkles,
  ChevronRight,
  Eye,
  Calendar,
} from 'lucide-react';
import { motion } from 'motion/react';
import { TimelineEventItem, DocumentItem } from '../types';

interface TimelineViewProps {
  events: TimelineEventItem[];
  documents: DocumentItem[];
  onSelectDocument: (doc: DocumentItem) => void;
}

export const TimelineView: React.FC<TimelineViewProps> = ({
  events,
  documents,
  onSelectDocument,
}) => {
  const [selectedCategory, setSelectedCategory] = useState<string>('All');

  const categories = ['All', 'Certificates', 'Projects', 'Internships', 'Academics', 'Hackathons', 'Resume'];

  const filteredEvents = events.filter(
    (ev) => selectedCategory === 'All' || ev.category === selectedCategory
  );

  // Group events by year
  const eventsByYear = new Map<string, TimelineEventItem[]>();
  filteredEvents.forEach((ev) => {
    const year = ev.year || '2026';
    if (!eventsByYear.has(year)) {
      eventsByYear.set(year, []);
    }
    eventsByYear.get(year)?.push(ev);
  });

  const sortedYears = Array.from(eventsByYear.keys()).sort((a, b) => a.localeCompare(b));

  const getEventIcon = (category: string) => {
    switch (category) {
      case 'Certificates':
        return <Award className="w-4 h-4 text-sky-400" />;
      case 'Projects':
        return <Code className="w-4 h-4 text-blue-400" />;
      case 'Internships':
        return <Briefcase className="w-4 h-4 text-emerald-400" />;
      case 'Hackathons':
        return <Sparkles className="w-4 h-4 text-purple-400" />;
      default:
        return <GraduationCap className="w-4 h-4 text-indigo-400" />;
    }
  };

  return (
    <div className="p-4 lg:p-8 space-y-6 max-w-5xl mx-auto text-white">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/10 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center space-x-3">
            <Clock className="w-6 h-6 text-sky-400" />
            <span>Digital Journey Timeline</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Chronological evolution of your verified academic achievements, hackathons, and industry experience.
          </p>
        </div>

        {/* Category Pills */}
        <div className="flex items-center space-x-2 overflow-x-auto pb-1 no-scrollbar">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`px-3 py-1.5 rounded-xl text-xs font-medium whitespace-nowrap transition-all ${
                selectedCategory === cat
                  ? 'bg-sky-500 text-slate-950 font-bold shadow-md shadow-sky-500/20'
                  : 'bg-slate-900/80 text-slate-300 hover:text-white border border-white/10'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Vertical Timeline Stack */}
      <div className="relative pl-6 md:pl-10 space-y-12 before:absolute before:left-3 md:before:left-5 before:top-3 before:bottom-3 before:w-0.5 before:bg-gradient-to-b before:from-sky-500 before:via-blue-600 before:to-indigo-500">
        {sortedYears.map((year) => {
          const yearEvents = eventsByYear.get(year) || [];
          return (
            <div key={year} className="space-y-6 relative">
              {/* Year Marker Badge */}
              <div className="flex items-center space-x-3 -ml-6 md:-ml-10 mb-4">
                <div className="w-6 h-6 md:w-8 md:h-8 rounded-full bg-sky-500 text-slate-950 font-bold text-xs flex items-center justify-center ring-4 ring-[#071326] shadow-lg shadow-sky-500/30">
                  {year.slice(-2)}
                </div>
                <span className="text-xl font-extrabold text-white font-mono tracking-wider">{year}</span>
              </div>

              {/* Event Cards */}
              <div className="space-y-4">
                {yearEvents.map((ev, idx) => {
                  const linkedDoc = documents.find((d) => d.id === ev.docId);

                  return (
                    <motion.div
                      key={ev.id || idx}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.3, delay: idx * 0.1 }}
                      className="p-5 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 hover:border-sky-500/40 transition-all backdrop-blur-md relative space-y-3 shadow-xl group"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-2">
                          <div className="p-1.5 rounded-lg bg-sky-500/10 border border-sky-500/20">
                            {getEventIcon(ev.category)}
                          </div>
                          <span className="px-2 py-0.5 rounded bg-sky-500/15 text-sky-300 font-mono text-[10px] font-bold uppercase">
                            {ev.category}
                          </span>
                        </div>
                        <span className="text-xs text-slate-400 font-mono flex items-center space-x-1">
                          <Calendar className="w-3 h-3 text-sky-400" />
                          <span>{ev.date}</span>
                        </span>
                      </div>

                      <h3 className="text-base font-bold text-white group-hover:text-sky-300 transition-colors">
                        {ev.title}
                      </h3>

                      <p className="text-xs text-slate-300 leading-relaxed">{ev.description}</p>

                      <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-white/10">
                        <div className="flex flex-wrap gap-1">
                          {ev.skills.map((s, sIdx) => (
                            <span
                              key={sIdx}
                              className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]"
                            >
                              {s}
                            </span>
                          ))}
                        </div>

                        {linkedDoc && (
                          <button
                            onClick={() => onSelectDocument(linkedDoc)}
                            className="text-xs text-sky-400 hover:text-sky-300 font-semibold flex items-center space-x-1"
                          >
                            <Eye className="w-3.5 h-3.5" />
                            <span>View Document</span>
                          </button>
                        )}
                      </div>
                    </motion.div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
