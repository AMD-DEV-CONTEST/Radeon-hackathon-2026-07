import React, { useState, useEffect } from 'react';
import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import { 
  LayoutDashboard, FileText, Users, Map, MessageSquare, 
  Settings, User, LogOut, Sun, Moon, Bell, BellRing, 
  Menu, X, Sparkles, Award
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import axios from 'axios';

interface LayoutProps {
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  const { user, logout, refreshProfile } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isNotificationOpen, setIsNotificationOpen] = useState(false);
  const [notifications, setNotifications] = useState<any[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);

  // Close menus on page change
  useEffect(() => {
    setIsMobileMenuOpen(false);
    setIsNotificationOpen(false);
  }, [location]);

  // Fetch notifications
  const fetchNotifications = async () => {
    try {
      const response = await axios.get('/api/dashboard/notifications');
      setNotifications(response.data);
      setUnreadCount(response.data.filter((n: any) => !n.isRead).length);
    } catch (err) {
      console.error('[Notifications] Failed to load:', err);
    }
  };

  useEffect(() => {
    if (user) {
      fetchNotifications();
      // Poll notifications every 30 seconds
      const timer = setInterval(fetchNotifications, 30000);
      return () => clearInterval(timer);
    }
  }, [user]);

  const handleMarkNotificationsAsRead = async () => {
    try {
      await axios.put('/api/dashboard/notifications/read');
      setUnreadCount(0);
      setNotifications(prev => prev.map(n => ({ ...n, isRead: true })));
      refreshProfile(); // Sync badges
    } catch (err) {
      console.error('[Notifications] Failed to clear alerts:', err);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const menuItems = [
    { name: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
    { name: 'Resume Critic', path: '/resume-analyzer', icon: FileText },
    { name: 'Mock Interview', path: '/interview', icon: Users },
    { name: 'Skill Gap', path: '/skill-gap', icon: Sparkles },
    { name: 'Learning Roadmap', path: '/roadmap', icon: Map },
    { name: 'AI Mentor Chat', path: '/chat', icon: MessageSquare },
    { name: 'Profile & Badges', path: '/profile', icon: User },
    { name: 'System Settings', path: '/settings', icon: Settings },
  ];

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-transparent">
      
      {/* SIDEBAR - DESKTOP */}
      <aside className="hidden md:flex flex-col w-72 glass-panel border-r border-dark-800/40 p-6 fixed h-screen z-50">
        
        {/* Logo and Brand */}
        <div className="flex items-center gap-3 mb-8 cursor-pointer" onClick={() => navigate('/dashboard')}>
          <div className="w-10 h-10 bg-gradient-to-tr from-primary-600 to-cyan-500 rounded-xl flex items-center justify-center text-white font-bold shadow-lg shadow-primary-500/20">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="6">
              <path d="M50 15 L58 42 L85 50 L58 58 L50 85 L42 58 L15 50 L42 42 Z" fill="currentColor"/>
            </svg>
          </div>
          <div>
            <h1 className="font-bold text-lg leading-none bg-gradient-to-r from-primary-400 to-cyan-400 bg-clip-text text-transparent font-heading">
              CareerPilot
            </h1>
            <span className="text-[10px] text-dark-400 tracking-widest uppercase">AI Mentor</span>
          </div>
        </div>

        {/* Navigation Menu */}
        <nav className="flex-1 flex flex-col gap-1.5 overflow-y-auto">
          {menuItems.map(item => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) => 
                  `flex items-center gap-3.5 px-4 py-3 rounded-xl transition-all duration-300 font-medium text-sm group ${
                    isActive 
                      ? 'bg-gradient-to-r from-primary-600/20 to-cyan-500/10 border border-primary-500/25 text-primary-400' 
                      : 'text-dark-400 hover:text-dark-200 hover:bg-dark-900/45 border border-transparent'
                  }`
                }
              >
                <Icon className="w-5 h-5 transition-transform group-hover:scale-110" />
                {item.name}
              </NavLink>
            );
          })}
        </nav>

        {/* User profile section at the bottom */}
        <div className="pt-4 border-t border-dark-800/40 flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center font-bold text-white uppercase text-sm shadow-md">
              {user?.name ? user.name.substring(0, 2) : 'CP'}
            </div>
            <div className="flex-1 min-w-0">
              <h4 className="font-bold text-sm text-dark-100 truncate">{user?.name}</h4>
              <p className="text-[11px] text-dark-400 truncate">{user?.targetCareer || 'Career Explorer'}</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 w-full px-4 py-2.5 rounded-xl text-xs font-semibold text-rose-400 hover:text-rose-300 hover:bg-rose-950/20 border border-transparent hover:border-rose-900/30 transition-all"
          >
            <LogOut className="w-4 h-4" />
            Logout Account
          </button>
        </div>
      </aside>

      {/* TOP HEADER & MOBILE NAVIGATION BAR */}
      <div className="flex-1 flex flex-col md:pl-72">
        <header className="glass-panel border-b border-dark-800/20 h-16 px-4 md:px-8 flex items-center justify-between sticky top-0 z-40 backdrop-blur-md">
          
          {/* Mobile hamburger menu toggle */}
          <div className="flex items-center gap-3 md:hidden">
            <button
              onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
              className="p-2 text-dark-400 hover:text-dark-200 hover:bg-dark-900/50 rounded-xl transition-all"
            >
              {isMobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
            </button>
            <div className="flex items-center gap-2" onClick={() => navigate('/dashboard')}>
              <div className="w-8 h-8 bg-gradient-to-tr from-primary-600 to-cyan-500 rounded-lg flex items-center justify-center text-white font-bold">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="6">
                  <path d="M50 15 L58 42 L85 50 L58 58 L50 85 L42 58 L15 50 L42 42 Z" fill="currentColor"/>
                </svg>
              </div>
              <h1 className="font-bold text-base font-heading">CareerPilot</h1>
            </div>
          </div>

          {/* Desktop target indicators */}
          <div className="hidden md:flex items-center gap-2 text-xs font-semibold text-dark-400">
            <span>Target Goal:</span>
            <span className="px-2.5 py-1 bg-primary-950/50 border border-primary-500/20 text-primary-400 rounded-lg flex items-center gap-1.5 shadow-sm">
              <Sparkles className="w-3.5 h-3.5" />
              {user?.targetCareer || 'Set Target Career in Settings'}
            </span>
          </div>

          {/* Top-right quick actions bar (theme, notifications, user avatar) */}
          <div className="flex items-center gap-3 relative">
            
            {/* Theme Toggle button */}
            <button
              onClick={toggleTheme}
              className="p-2 rounded-xl border border-dark-800/40 hover:border-primary-500/20 text-dark-400 hover:text-primary-400 hover:bg-dark-900/50 transition-all duration-300"
              title={theme === 'dark' ? 'Activate Light Mode' : 'Activate Dark Mode'}
            >
              {theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
            </button>

            {/* Notification drop-down bell panel */}
            <div className="relative">
              <button
                onClick={() => setIsNotificationOpen(!isNotificationOpen)}
                className={`p-2 rounded-xl border border-dark-800/40 hover:border-primary-500/20 text-dark-400 hover:text-primary-400 hover:bg-dark-900/50 transition-all duration-300 relative ${
                  unreadCount > 0 ? 'text-primary-400 border-primary-500/10' : ''
                }`}
              >
                {unreadCount > 0 ? (
                  <>
                    <BellRing className="w-5 h-5 text-primary-400 animate-pulse-glow" />
                    <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-gradient-to-r from-primary-500 to-cyan-500 rounded-full" />
                  </>
                ) : (
                  <Bell className="w-5 h-5" />
                )}
              </button>

              {/* Real-time Notifications list dropdown overlay */}
              {isNotificationOpen && (
                <div className="absolute right-0 mt-3 w-80 glass-panel rounded-2xl shadow-2xl p-4 border border-dark-800/60 flex flex-col gap-3 z-50">
                  <div className="flex items-center justify-between border-b border-dark-800/40 pb-2">
                    <h3 className="font-bold text-sm text-dark-100 flex items-center gap-1.5">
                      <Bell className="w-4 h-4 text-primary-400" />
                      In-App Notifications
                    </h3>
                    {unreadCount > 0 && (
                      <button
                        onClick={handleMarkNotificationsAsRead}
                        className="text-[10px] text-primary-400 hover:text-primary-300 font-semibold uppercase tracking-wider transition-all"
                      >
                        Clear All
                      </button>
                    )}
                  </div>
                  <div className="max-h-64 overflow-y-auto flex flex-col gap-2.5">
                    {notifications.length === 0 ? (
                      <div className="text-center py-6 text-xs text-dark-500">
                        No notifications or alerts
                      </div>
                    ) : (
                      notifications.map((notif, index) => (
                        <div
                          key={notif._id || index}
                          className={`p-2.5 rounded-xl border transition-all ${
                            notif.isRead 
                              ? 'bg-dark-950/20 border-dark-900/50 opacity-60' 
                              : 'bg-primary-950/20 border-primary-500/20'
                          }`}
                        >
                          <div className="flex items-start gap-2">
                            {notif.type === 'achievement' ? (
                              <Award className="w-4 h-4 text-yellow-400 shrink-0 mt-0.5" />
                            ) : (
                              <Sparkles className="w-4 h-4 text-primary-400 shrink-0 mt-0.5" />
                            )}
                            <div>
                              <h4 className="font-bold text-xs text-dark-100 leading-snug">{notif.title}</h4>
                              <p className="text-[10px] text-dark-400 leading-normal mt-0.5">{notif.message}</p>
                              <span className="text-[8px] text-dark-500 block mt-1">
                                {new Date(notif.createdAt).toLocaleDateString()}
                              </span>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Mobile user profile button shortcut */}
            <div 
              onClick={() => navigate('/profile')}
              className="w-8.5 h-8.5 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center font-bold text-white uppercase text-xs cursor-pointer shadow-md md:hidden"
            >
              {user?.name ? user.name.substring(0, 2) : 'CP'}
            </div>
          </div>
        </header>

        {/* CONTENT PANEL */}
        <main className="flex-1 p-4 md:p-8 overflow-x-hidden">
          <div className="max-w-6xl mx-auto animate-fade-in">
            {children}
          </div>
        </main>
      </div>

      {/* MOBILE FULL DRAWER NAVIGATION */}
      {isMobileMenuOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          {/* Backdrop shadow overlay */}
          <div className="fixed inset-0 bg-dark-950/80 backdrop-blur-sm" onClick={() => setIsMobileMenuOpen(false)} />
          
          <div className="relative flex flex-col w-4/5 max-w-sm bg-dark-950/95 border-r border-dark-800/40 p-6 z-50 h-full shadow-2xl">
            <button
              onClick={() => setIsMobileMenuOpen(false)}
              className="absolute top-4 right-4 p-2 text-dark-400 hover:text-dark-200"
            >
              <X className="w-6 h-6" />
            </button>

            <div className="flex items-center gap-3 mb-8 cursor-pointer" onClick={() => { navigate('/dashboard'); setIsMobileMenuOpen(false); }}>
              <div className="w-9 h-9 bg-gradient-to-tr from-primary-600 to-cyan-500 rounded-lg flex items-center justify-center text-white font-bold">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="6">
                  <path d="M50 15 L58 42 L85 50 L58 58 L50 85 L42 58 L15 50 L42 42 Z" fill="currentColor"/>
                </svg>
              </div>
              <h1 className="font-bold text-base font-heading bg-gradient-to-r from-primary-400 to-cyan-400 bg-clip-text text-transparent">CareerPilot</h1>
            </div>

            <nav className="flex-1 flex flex-col gap-1 overflow-y-auto">
              {menuItems.map(item => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    onClick={() => setIsMobileMenuOpen(false)}
                    className={({ isActive }) => 
                      `flex items-center gap-3.5 px-4 py-3.5 rounded-xl transition-all duration-300 font-medium text-sm ${
                        isActive 
                          ? 'bg-gradient-to-r from-primary-600/20 to-cyan-500/10 border border-primary-500/20 text-primary-400 font-semibold' 
                          : 'text-dark-400 hover:text-dark-200 hover:bg-dark-900/40 border border-transparent'
                      }`
                    }
                  >
                    <Icon className="w-5 h-5" />
                    {item.name}
                  </NavLink>
                );
              })}
            </nav>

            <div className="pt-4 border-t border-dark-800/40 flex flex-col gap-3 mt-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center font-bold text-white uppercase">
                  {user?.name ? user.name.substring(0, 2) : 'CP'}
                </div>
                <div>
                  <h4 className="font-bold text-sm text-dark-100">{user?.name}</h4>
                  <p className="text-xs text-dark-400">{user?.targetCareer || 'Career Explorer'}</p>
                </div>
              </div>
              <button
                onClick={handleLogout}
                className="flex items-center justify-center gap-3 w-full px-4 py-2.5 rounded-xl text-xs font-bold text-rose-400 hover:bg-rose-950/20 border border-rose-900/20 transition-all"
              >
                <LogOut className="w-4 h-4" />
                Logout Account
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Layout;
