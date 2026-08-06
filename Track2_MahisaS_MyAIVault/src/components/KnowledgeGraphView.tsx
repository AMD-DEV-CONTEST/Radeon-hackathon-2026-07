import React, { useState } from 'react';
import {
  Network,
  Award,
  Code,
  FileText,
  Briefcase,
  GraduationCap,
  Sparkles,
  Info,
  CheckCircle2,
  ChevronRight,
  RefreshCw,
} from 'lucide-react';
import { GraphNode, GraphLink } from '../types';

interface KnowledgeGraphViewProps {
  nodes: GraphNode[];
  links: GraphLink[];
}

export const KnowledgeGraphView: React.FC<KnowledgeGraphViewProps> = ({ nodes, links }) => {
  const [selectedNodeId, setSelectedNodeId] = useState<string>('n_cert_python');
  const [filterType, setFilterType] = useState<string>('all');

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) || nodes[0];

  const connectedLinks = links.filter(
    (l) => l.source === selectedNodeId || l.target === selectedNodeId
  );

  const connectedNodeIds = new Set<string>();
  connectedLinks.forEach((l) => {
    connectedNodeIds.add(l.source);
    connectedNodeIds.add(l.target);
  });

  const getNodeIcon = (type: string) => {
    switch (type) {
      case 'certificate':
        return <Award className="w-4 h-4 text-sky-400" />;
      case 'skill':
        return <Code className="w-4 h-4 text-indigo-400" />;
      case 'project':
        return <FileText className="w-4 h-4 text-blue-400" />;
      case 'internship':
        return <Briefcase className="w-4 h-4 text-emerald-400" />;
      case 'goal':
        return <GraduationCap className="w-4 h-4 text-purple-400" />;
      default:
        return <Network className="w-4 h-4 text-slate-400" />;
    }
  };

  const getNodeColor = (type: string) => {
    switch (type) {
      case 'certificate':
        return 'border-sky-500 bg-sky-500/20 text-sky-300';
      case 'skill':
        return 'border-indigo-500 bg-indigo-500/20 text-indigo-300';
      case 'project':
        return 'border-blue-500 bg-blue-500/20 text-blue-300';
      case 'internship':
        return 'border-emerald-500 bg-emerald-500/20 text-emerald-300';
      case 'goal':
        return 'border-purple-500 bg-purple-500/20 text-purple-300';
      default:
        return 'border-slate-500 bg-slate-500/20 text-slate-300';
    }
  };

  const filteredNodes = nodes.filter((n) => filterType === 'all' || n.type === filterType);

  return (
    <div className="p-4 lg:p-8 space-y-6 max-w-7xl mx-auto text-white">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/10 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center space-x-3">
            <Network className="w-6 h-6 text-sky-400" />
            <span>Interactive Knowledge Graph</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Visualizing how your certificates, skills, projects, and work experience connect to your target career goal.
          </p>
        </div>

        {/* Node Category Filters */}
        <div className="flex items-center space-x-2 overflow-x-auto pb-1">
          {['all', 'certificate', 'skill', 'project', 'internship', 'goal'].map((t) => (
            <button
              key={t}
              onClick={() => setFilterType(t)}
              className={`px-3 py-1.5 rounded-xl text-xs font-medium capitalize whitespace-nowrap transition-all ${
                filterType === t
                  ? 'bg-sky-500 text-slate-950 font-bold'
                  : 'bg-slate-900/80 text-slate-300 hover:text-white border border-white/10'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Main Graph Canvas & Inspector Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Interactive SVG Node Canvas */}
        <div className="lg:col-span-2 p-6 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 relative overflow-hidden min-h-[480px] flex flex-col justify-between shadow-2xl">
          {/* Subtle Grid Pattern */}
          <div
            className="absolute inset-0 opacity-[0.05] pointer-events-none"
            style={{
              backgroundImage: `radial-gradient(#4F9DFF 1px, transparent 1px)`,
              backgroundSize: '24px 24px',
            }}
          />

          <div className="relative z-10 flex items-center justify-between text-xs text-slate-400 font-mono mb-4">
            <div className="flex items-center space-x-2">
              <Sparkles className="w-4 h-4 text-sky-400" />
              <span>Click any node to inspect connected credentials</span>
            </div>
            <span className="bg-sky-500/10 text-sky-300 px-2 py-0.5 rounded border border-sky-500/20">
              {filteredNodes.length} Active Nodes
            </span>
          </div>

          {/* Connected Example Chain Banner */}
          <div className="relative z-10 p-3 rounded-xl bg-slate-900/90 border border-sky-500/20 text-xs mb-6 overflow-x-auto">
            <span className="text-[10px] text-slate-400 font-mono uppercase block mb-1">
              Sample Connected Flow Path:
            </span>
            <div className="flex items-center space-x-2 text-white font-medium whitespace-nowrap">
              <span className="text-sky-300">Stanford Python Cert</span>
              <span className="text-slate-500">→</span>
              <span className="text-indigo-300">Python Skill</span>
              <span className="text-slate-500">→</span>
              <span className="text-blue-300">Banking Risk Project</span>
              <span className="text-slate-500">→</span>
              <span className="text-emerald-300">Goldman Sachs Intern</span>
              <span className="text-slate-500">→</span>
              <span className="text-purple-300">AI Engineer Goal</span>
            </div>
          </div>

          {/* Interactive Graph Node Web */}
          <div className="relative z-10 h-80 w-full flex items-center justify-center">
            <svg className="absolute inset-0 w-full h-full pointer-events-none">
              {links.map((link, idx) => {
                const srcNode = nodes.find((n) => n.id === link.source);
                const tgtNode = nodes.find((n) => n.id === link.target);
                if (!srcNode || !tgtNode) return null;

                const isHighlighted =
                  link.source === selectedNodeId || link.target === selectedNodeId;

                return (
                  <g key={idx}>
                    <line
                      x1={srcNode.x}
                      y1={srcNode.y}
                      x2={tgtNode.x}
                      y2={tgtNode.y}
                      stroke={isHighlighted ? '#4F9DFF' : '#334155'}
                      strokeWidth={isHighlighted ? 2.5 : 1}
                      strokeDasharray={isHighlighted ? 'none' : '4 4'}
                    />
                  </g>
                );
              })}
            </svg>

            {/* Nodes overlay */}
            <div className="relative w-full h-full">
              {filteredNodes.map((node) => {
                const isSelected = node.id === selectedNodeId;
                const isConnected = connectedNodeIds.has(node.id);

                return (
                  <button
                    key={node.id}
                    onClick={() => setSelectedNodeId(node.id)}
                    style={{ left: `${node.x || 100}px`, top: `${node.y || 100}px` }}
                    className={`absolute -translate-x-1/2 -translate-y-1/2 p-3 rounded-2xl border transition-all duration-300 flex items-center space-x-2 shadow-xl ${getNodeColor(
                      node.type
                    )} ${
                      isSelected
                        ? 'ring-4 ring-sky-400 scale-110 z-30 shadow-sky-500/50'
                        : isConnected
                        ? 'opacity-100 z-20'
                        : 'opacity-70 hover:opacity-100 z-10'
                    }`}
                  >
                    {getNodeIcon(node.type)}
                    <span className="text-xs font-bold text-white whitespace-nowrap">{node.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Node Inspector Side-Panel */}
        <div className="p-6 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-6 shadow-2xl flex flex-col justify-between">
          <div className="space-y-4">
            <div className="flex items-center space-x-3 border-b border-white/10 pb-4">
              <div className="p-3 rounded-xl bg-sky-500/20 text-sky-400">
                {getNodeIcon(selectedNode.type)}
              </div>
              <div>
                <span className="text-[10px] text-sky-400 font-mono uppercase font-bold tracking-wider">
                  {selectedNode.type} Node
                </span>
                <h3 className="text-base font-bold text-white">{selectedNode.label}</h3>
              </div>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <span className="text-slate-400 block mb-1">Description:</span>
                <p className="text-slate-200 leading-relaxed bg-slate-900/80 p-3 rounded-xl border border-white/5">
                  {selectedNode.description || 'Verified node in student digital identity graph.'}
                </p>
              </div>

              <div>
                <span className="text-slate-400 block mb-1">Connected Graph Links ({connectedLinks.length}):</span>
                <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                  {connectedLinks.map((link, idx) => {
                    const otherId = link.source === selectedNodeId ? link.target : link.source;
                    const otherNode = nodes.find((n) => n.id === otherId);
                    return (
                      <div
                        key={idx}
                        onClick={() => setSelectedNodeId(otherId)}
                        className="p-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/5 flex items-center justify-between cursor-pointer transition-colors"
                      >
                        <div className="flex items-center space-x-2">
                          <span className="text-sky-400 font-mono text-[10px]">{link.label}</span>
                          <span className="text-white font-medium">{otherNode?.label}</span>
                        </div>
                        <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          <div className="p-3.5 rounded-xl bg-sky-500/10 border border-sky-500/20 text-xs text-slate-300">
            <div className="flex items-center space-x-2 font-bold text-sky-300 mb-1">
              <CheckCircle2 className="w-4 h-4" />
              <span>AI Knowledge Connection</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Gemini AI automatically maps new uploaded certificates to existing skills and career goals.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
