import React from 'react';
import {
  LayoutDashboard,
  FileText,
  Clock,
  Network,
  Bot,
  TrendingUp,
  BarChart3,
  Settings,
  Sparkles,
  ShieldCheck,
} from 'lucide-react';
import { UserProfile } from '../types';

interface SidebarProps {
  activeTab: string;
  user: UserProfile;
  docCount: number;
  onNavigate: (tab: string) => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  user,
  docCount,
  onNavigate,
  mobileOpen,
  onCloseMobile,
}) => {
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard className="w-4 h-4" /> },
    { id: 'documents', label: 'Documents Vault', icon: <FileText className="w-4 h-4" />, badge: docCount },
    { id: 'timeline', label: 'Digital Timeline', icon: <Clock className="w-4 h-4" /> },
    { id: 'graph', label: 'Knowledge Graph', icon: <Network className="w-4 h-4" /> },
    { id: 'chat', label: 'AI Assistant', icon: <Bot className="w-4 h-4" />, highlight: true },
    { id: 'insights', label: 'Career Insights', icon: <TrendingUp className="w-4 h-4" /> },
    { id: 'analytics', label: 'Analytics', icon: <BarChart3 className="w-4 h-4" /> },
    { id: 'settings', label: 'Settings', icon: <Settings className="w-4 h-4" /> },
  ];

  const handleSelect = (id: string) => {
    onNavigate(id);
    onCloseMobile();
  };

  return (
    <>
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          onClick={onCloseMobile}
          className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm lg:hidden"
        />
      )}

      <aside
        className={`fixed lg:static top-0 left-0 bottom-0 z-50 w-64 bg-[#0B1F3A] border-r border-white/10 flex flex-col justify-between transition-transform duration-300 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        <div className="p-4 space-y-6 overflow-y-auto">
          {/* Top Label */}
          <div className="px-3 pt-2 flex items-center justify-between text-xs text-slate-400 font-mono uppercase tracking-wider">
            <span>Navigation</span>
            <span className="flex items-center text-[10px] text-sky-400 bg-sky-500/10 px-2 py-0.5 rounded border border-sky-500/20">
              <Sparkles className="w-3 h-3 mr-1" />
              v2.4 AI
            </span>
          </div>

          {/* Navigation Items */}
          <nav className="space-y-1.5">
            {navItems.map((item) => {
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => handleSelect(item.id)}
                  className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
                    isActive
                      ? 'bg-gradient-to-r from-sky-500 to-blue-600 text-white shadow-lg shadow-sky-500/20'
                      : item.highlight
                      ? 'bg-sky-500/10 text-sky-300 hover:bg-sky-500/20 hover:text-white border border-sky-500/30'
                      : 'text-slate-300 hover:text-white hover:bg-white/5'
                  }`}
                >
                  <div className="flex items-center space-x-3">
                    <span className={isActive ? 'text-white' : 'text-sky-400'}>{item.icon}</span>
                    <span>{item.label}</span>
                  </div>
                  {item.badge !== undefined && (
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-mono ${
                        isActive ? 'bg-white/20 text-white' : 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          {/* Quick AI Status Box */}
          <div className="p-3.5 rounded-2xl bg-gradient-to-b from-slate-900/90 to-blue-950/60 border border-sky-500/20 text-xs text-slate-300 space-y-2">
            <div className="flex items-center space-x-2 text-sky-400 font-bold">
              <ShieldCheck className="w-4 h-4" />
              <span>Identity Vault Active</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Gemini AI is actively vectorizing and connecting your credentials.
            </p>
          </div>
        </div>

        {/* Bottom User Card */}
        <div className="p-4 border-t border-white/10 bg-slate-900/50">
          <div className="flex items-center space-x-3">
            <img
              src={user.avatarUrl}
              alt={user.name}
              className="w-9 h-9 rounded-xl object-cover ring-2 ring-sky-500/40"
            />
            <div className="overflow-hidden">
              <div className="text-xs font-bold text-white truncate">{user.name}</div>
              <div className="text-[10px] text-sky-400 font-mono truncate">{user.university}</div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
};
