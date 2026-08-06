import React, { useState } from 'react';
import {
  Bot,
  Search,
  Bell,
  Upload,
  User,
  Settings,
  LogOut,
  Menu,
  X,
  Sparkles,
  RefreshCw,
  CheckCircle2,
} from 'lucide-react';
import { UserProfile, AppNotification } from '../types';

interface TopNavProps {
  user: UserProfile;
  notifications: AppNotification[];
  onOpenUpload: () => void;
  onNavigate: (tab: string) => void;
  onSearch: (query: string) => void;
  onSignOut: () => void;
  onResetData: () => void;
  onToggleMobileMenu: () => void;
}

export const TopNav: React.FC<TopNavProps> = ({
  user,
  notifications,
  onOpenUpload,
  onNavigate,
  onSearch,
  onSignOut,
  onResetData,
  onToggleMobileMenu,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [showNotifications, setShowNotifications] = useState(false);
  const [showProfileMenu, setShowProfileMenu] = useState(false);

  const unreadCount = notifications.filter((n) => !n.read).length;

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      onSearch(searchQuery);
      onNavigate('search');
    }
  };

  return (
    <header className="sticky top-0 z-40 bg-[#0B1F3A]/90 border-b border-white/10 backdrop-blur-xl px-4 lg:px-8 py-3.5 flex items-center justify-between">
      {/* Left Brand & Mobile Toggle */}
      <div className="flex items-center space-x-3">
        <button
          onClick={onToggleMobileMenu}
          className="lg:hidden p-2 text-slate-300 hover:text-white rounded-lg hover:bg-white/5"
        >
          <Menu className="w-5 h-5" />
        </button>

        <div
          onClick={() => onNavigate('dashboard')}
          className="flex items-center space-x-3 cursor-pointer group"
        >
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-sky-500 via-blue-600 to-indigo-400 p-[1px] flex items-center justify-center shadow-lg shadow-sky-500/20 group-hover:scale-105 transition-transform">
            <div className="w-full h-full bg-[#0B1F3A] rounded-[11px] flex items-center justify-center">
              <Bot className="w-5 h-5 text-sky-400" />
            </div>
          </div>
          <div className="hidden sm:block">
            <span className="text-lg font-bold text-white tracking-tight group-hover:text-sky-300 transition-colors">
              MyAI Vault
            </span>
            <span className="block text-[10px] text-sky-400 font-mono tracking-wider -mt-1 uppercase">
              AI Identity System
            </span>
          </div>
        </div>
      </div>

      {/* Center Semantic Vector Search Input */}
      <form onSubmit={handleSearchSubmit} className="flex-1 max-w-md mx-4 hidden md:block">
        <div className="relative">
          <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-2.5" />
          <input
            type="text"
            placeholder="AI Search: 'Show Python certificates', 'Latest resume'..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-slate-900/80 border border-white/10 rounded-xl pl-10 pr-12 py-2 text-xs text-white placeholder-slate-400 focus:outline-none focus:border-sky-400/80 transition-colors shadow-inner"
          />
          <button
            type="submit"
            className="absolute right-2 top-1.5 px-2 py-0.5 rounded-lg bg-sky-500/20 hover:bg-sky-500/30 text-sky-300 text-[10px] font-mono font-medium border border-sky-500/30"
          >
            Ask AI
          </button>
        </div>
      </form>

      {/* Right Controls */}
      <div className="flex items-center space-x-3">
        {/* Upload Button CTA */}
        <button
          onClick={onOpenUpload}
          className="flex items-center space-x-2 px-3.5 py-2 rounded-xl bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-white font-semibold text-xs shadow-md shadow-sky-500/20 transition-all transform hover:-translate-y-0.5"
        >
          <Upload className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Upload Document</span>
        </button>

        {/* Notifications Dropdown */}
        <div className="relative">
          <button
            onClick={() => {
              setShowNotifications(!showNotifications);
              setShowProfileMenu(false);
            }}
            className="p-2 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 hover:text-white relative transition-colors"
          >
            <Bell className="w-4 h-4" />
            {unreadCount > 0 && (
              <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-sky-400 ring-4 ring-[#0B1F3A]" />
            )}
          </button>

          {showNotifications && (
            <div className="absolute right-0 mt-2 w-80 bg-[#0B1F3A] border border-white/10 rounded-2xl shadow-2xl py-3 z-50 text-white">
              <div className="px-4 pb-2 border-b border-white/10 flex items-center justify-between text-xs">
                <span className="font-bold">AI Vault Notifications</span>
                <span className="text-[10px] text-sky-400 font-mono">{unreadCount} New</span>
              </div>
              <div className="max-h-64 overflow-y-auto divide-y divide-white/5 text-xs">
                {notifications.length === 0 ? (
                  <div className="p-4 text-center text-slate-400">No notifications</div>
                ) : (
                  notifications.map((n) => (
                    <div key={n.id} className="p-3 hover:bg-white/5 transition-colors">
                      <div className="flex items-center justify-between mb-1">
                        <strong className="text-sky-300">{n.title}</strong>
                        <span className="text-[10px] text-slate-500">{n.timestamp}</span>
                      </div>
                      <p className="text-slate-300 text-[11px] leading-relaxed">{n.message}</p>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        {/* Profile Avatar & Menu */}
        <div className="relative">
          <button
            onClick={() => {
              setShowProfileMenu(!showProfileMenu);
              setShowNotifications(false);
            }}
            className="flex items-center space-x-2 p-1 rounded-xl hover:bg-white/5 transition-colors border border-transparent hover:border-white/10"
          >
            <img
              src={user.avatarUrl}
              alt={user.name}
              className="w-8 h-8 rounded-lg object-cover ring-2 ring-sky-500/40"
            />
            <span className="hidden xl:inline text-xs font-semibold text-white max-w-[120px] truncate">
              {user.name}
            </span>
          </button>

          {showProfileMenu && (
            <div className="absolute right-0 mt-2 w-56 bg-[#0B1F3A] border border-white/10 rounded-2xl shadow-2xl py-2 z-50 text-white text-xs">
              <div className="px-4 py-2 border-b border-white/10 mb-1">
                <strong className="block text-white font-semibold truncate">{user.name}</strong>
                <span className="text-[10px] text-slate-400 block truncate">{user.email}</span>
                <span className="inline-block mt-1 px-2 py-0.5 rounded bg-sky-500/15 text-sky-300 font-mono text-[9px]">
                  {user.targetRole}
                </span>
              </div>

              <button
                onClick={() => {
                  onNavigate('settings');
                  setShowProfileMenu(false);
                }}
                className="w-full text-left px-4 py-2 hover:bg-white/5 flex items-center space-x-2 text-slate-300 hover:text-white"
              >
                <Settings className="w-3.5 h-3.5 text-sky-400" />
                <span>Vault Settings</span>
              </button>

              <button
                onClick={() => {
                  onResetData();
                  setShowProfileMenu(false);
                }}
                className="w-full text-left px-4 py-2 hover:bg-white/5 flex items-center space-x-2 text-slate-300 hover:text-white"
              >
                <RefreshCw className="w-3.5 h-3.5 text-indigo-400" />
                <span>Reset Sample Data</span>
              </button>

              <div className="border-t border-white/10 mt-1 pt-1">
                <button
                  onClick={() => {
                    onSignOut();
                    setShowProfileMenu(false);
                  }}
                  className="w-full text-left px-4 py-2 hover:bg-red-500/10 flex items-center space-x-2 text-red-400"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span>Sign Out</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
