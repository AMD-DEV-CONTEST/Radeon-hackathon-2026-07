import React, { useState } from 'react';
import { Link, NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { 
  FiHome, FiMessageSquare, FiCheckSquare, FiGlobe, 
  FiBookOpen, FiActivity, FiShield, FiLogOut, FiMenu, FiX, FiUser 
} from 'react-icons/fi';
import { HiSun, HiMoon } from 'react-icons/hi2';

const Layout = () => {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const isChat = location.pathname === '/chat';

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  // Base navigation menu items
  const menuItems = [
    { name: 'Dashboard', path: '/', icon: <FiHome className="h-5 w-5" /> },
    { name: 'AI Chatbot', path: '/chat', icon: <FiMessageSquare className="h-5 w-5" /> },
    { name: 'Grammar Correction', path: '/grammar', icon: <FiCheckSquare className="h-5 w-5" /> },
    { name: 'Translation', path: '/translation', icon: <FiGlobe className="h-5 w-5" /> },
    { name: 'AI Quiz Generator', path: '/quiz', icon: <FiBookOpen className="h-5 w-5" /> },
    { name: 'Progress Tracker', path: '/progress', icon: <FiActivity className="h-5 w-5" /> },
  ];

  // If user is admin, append Admin Panel
  if (user?.roles?.includes('ROLE_ADMIN')) {
    menuItems.push({ name: 'Admin Dashboard', path: '/admin', icon: <FiShield className="h-5 w-5" /> });
  }

  const SidebarContent = () => (
    <div className="flex h-full flex-col justify-between p-4">
      <div className="space-y-6">
        {/* App Title */}
        <Link to="/" className="flex items-center gap-3 px-2 py-2">
          <img src="/logo.jpg" alt="LinguaBot" className="h-10 w-10 object-contain rounded-xl shadow-sm border border-gray-100 dark:border-slate-850" />
          <span className="text-xl font-extrabold tracking-tight bg-gradient-to-r from-primary-600 to-violet-500 bg-clip-text text-transparent dark:from-primary-400 dark:to-violet-400">
            LinguaBot
          </span>
        </Link>

        {/* Menu Navigation */}
        <nav className="space-y-1">
          {menuItems.map((item) => (
            <NavLink
              key={item.name}
              to={item.path}
              onClick={() => setMobileMenuOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition-all duration-150 ${
                  isActive
                    ? 'bg-primary-600 text-white shadow-md shadow-primary-600/10'
                    : 'text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-900 hover:text-gray-900 dark:hover:text-white'
                }`
              }
            >
              {item.icon}
              <span>{item.name}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      {/* Footer Profile & Controls */}
      <div className="space-y-4 pt-4 border-t border-gray-200 dark:border-slate-800">
        {/* Toggle Theme button */}
        <button
          onClick={toggleTheme}
          className="flex w-full items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-900 hover:text-gray-900 dark:hover:text-white transition"
        >
          {theme === 'dark' ? (
            <>
              <HiSun className="h-5 w-5 text-yellow-500" />
              <span>Light Mode</span>
            </>
          ) : (
            <>
              <HiMoon className="h-5 w-5 text-violet-600" />
              <span>Dark Mode</span>
            </>
          )}
        </button>

        {/* Profile Info */}
        <NavLink
          to="/profile"
          onClick={() => setMobileMenuOpen(false)}
          className={({ isActive }) =>
            `flex items-center justify-between p-2 rounded-xl border transition ${
              isActive
                ? 'bg-gray-100 dark:bg-slate-900 border-primary-500/30'
                : 'border-transparent hover:bg-gray-50 dark:hover:bg-slate-900'
            }`
          }
        >
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-100 dark:bg-primary-950/40 text-primary-600 dark:text-primary-400 border border-primary-200 dark:border-primary-900/30 font-bold">
              {user?.username?.charAt(0).toUpperCase() || 'U'}
            </div>
            <div className="text-left">
              <p className="text-xs font-bold text-gray-800 dark:text-white truncate max-w-[120px]">
                {user?.username}
              </p>
              <p className="text-[10px] text-gray-500 dark:text-slate-400 truncate max-w-[120px]">
                {user?.email}
              </p>
            </div>
          </div>
          <FiUser className="h-4 w-4 text-gray-400 hover:text-primary-600" />
        </NavLink>

        {/* Log Out button */}
        <button
          onClick={handleLogout}
          className="flex w-full items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20 transition"
        >
          <FiLogOut className="h-5 w-5" />
          <span>Log Out</span>
        </button>
      </div>
    </div>
  );

  return (
    <div className="flex min-h-screen bg-gray-50 dark:bg-slate-950 text-gray-900 dark:text-white font-sans transition-colors duration-200">
      {/* Desktop Sidebar (Pinned Left) */}
      <aside className="hidden md:flex md:w-64 md:flex-col fixed inset-y-0 bg-white dark:bg-slate-900 border-r border-gray-200 dark:border-slate-800/80 z-20 shadow-sm">
        <SidebarContent />
      </aside>

      {/* Mobile Header (Fixed Top) */}
      <div className="md:hidden flex h-16 items-center justify-between px-4 border-b border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 fixed top-0 w-full z-20 shadow-sm">
        <Link to="/" className="flex items-center gap-2">
          <img src="/logo.jpg" alt="LinguaBot" className="h-8 w-8 object-contain rounded-lg" />
          <span className="text-lg font-black tracking-tight text-gray-900 dark:text-white">
            LinguaBot
          </span>
        </Link>
        <button
          onClick={() => setMobileMenuOpen(true)}
          className="p-2 rounded-lg text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800"
        >
          <FiMenu className="h-6 w-6" />
        </button>
      </div>

      {/* Mobile Drawer (Overlay Slides In) */}
      {mobileMenuOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity"
            onClick={() => setMobileMenuOpen(false)}
          ></div>

          {/* Drawer content */}
          <div className="relative flex w-full max-w-xs flex-1 flex-col bg-white dark:bg-slate-900 border-r border-gray-200 dark:border-slate-800 animate-slide-in-right">
            <button
              onClick={() => setMobileMenuOpen(false)}
              className="absolute top-4 right-4 p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              <FiX className="h-6 w-6" />
            </button>
            <SidebarContent />
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <main className="flex-1 md:pl-64 pt-16 md:pt-0 min-h-screen flex flex-col">
        <div className={isChat ? "flex-1 flex flex-col h-full w-full" : "flex-1 p-6 md:p-8 max-w-7xl w-full mx-auto"}>
          {/* Viewport for nested route pages */}
          <Outlet />
        </div>
      </main>
    </div>
  );
};

export default Layout;
