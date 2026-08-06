import React from "react";
import { User, LogOut, ShieldAlert, Activity, HeartPulse, Sun, Moon } from "lucide-react";

interface NavbarProps {
  currentTab: string;
  setTab: (tab: string) => void;
  user: any;
  userProfile?: any;
  isGuest: boolean;
  onLogout: () => void;
  darkMode: boolean;
  toggleDarkMode: () => void;
}

export default function Navbar({ currentTab, setTab, user, userProfile, isGuest, onLogout, darkMode, toggleDarkMode }: NavbarProps) {
  const tabs = [
    { id: "dashboard", label: "Dashboard" },
    { id: "diseases", label: "Disease Library" },
    { id: "chatbot", label: "AI Assistant" },
    { id: "symptom-checker", label: "Symptom Checker" },
    { id: "emergency", label: "Emergency & Directory" },
    { id: "profile", label: "Profile" },
    { id: "about", label: "About" }
  ];

  return (
    <header id="app-header" className="sticky top-0 z-50 w-full bg-white dark:bg-slate-900 border-b border-slate-100 dark:border-slate-800 shadow-sm backdrop-blur-md bg-white/95 dark:bg-slate-900/95 transition-colors">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        
        {/* Professional Logo */}
        <div 
          id="brand-logo-container"
          onClick={() => setTab("dashboard")} 
          className="flex items-center gap-3 cursor-pointer group"
        >
          <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center text-white shadow-md shadow-blue-500/20 group-hover:bg-blue-700 transition-all duration-300">
            {/* SVG Logo: Medical Cross + Chat Bubble + Tech node */}
            <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" className="hidden" />
              {/* Custom Cross inside bubble */}
              <rect x="5" y="5" width="14" height="14" rx="4" className="stroke-blue-200" strokeWidth="1" />
              <path d="M12 8v8M8 12h8" />
              <circle cx="18" cy="6" r="1.5" fill="currentColor" className="text-emerald-400" />
            </svg>
          </div>
          <div>
            <span className="font-sans font-bold text-lg tracking-tight text-slate-900 dark:text-white group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
              HealthSphere <span className="text-blue-600 font-semibold">AI</span>
            </span>
            <span className="block text-[10px] font-mono tracking-wider text-slate-400 dark:text-slate-500 uppercase -mt-1 font-medium">
              Intelligent Public Health
            </span>
          </div>
        </div>

        {/* Desktop Navigation Links */}
        <nav id="desktop-nav-menu" className="hidden md:flex items-center gap-1">
          {tabs.map((tab) => (
            <button
              id={`nav-link-${tab.id}`}
              key={tab.id}
              onClick={() => setTab(tab.id)}
              className={`px-3.5 py-2 rounded-lg text-sm font-medium tracking-tight transition-all duration-200 cursor-pointer ${
                currentTab === tab.id
                  ? "bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400 shadow-sm"
                  : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {/* User Badge, Theme Toggle, and Session Actions */}
        <div id="user-actions-container" className="flex items-center gap-3">
          
          {/* Theme Toggle Button */}
          <button
            id="theme-toggle-btn"
            onClick={toggleDarkMode}
            className="p-2 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl transition-all cursor-pointer"
            title={darkMode ? "Switch to light mode" : "Switch to dark mode"}
          >
            {darkMode ? <Sun className="w-4.5 h-4.5 text-amber-400" /> : <Moon className="w-4.5 h-4.5 text-slate-600" />}
          </button>

          <div 
            onClick={() => !isGuest && setTab("profile")}
            className={`hidden lg:flex flex-col items-end text-right ${!isGuest ? "cursor-pointer hover:opacity-85 transition-opacity" : ""}`}
            title={!isGuest ? "View your user profile" : "Guest Mode"}
          >
            <span className="text-xs font-semibold text-slate-800 dark:text-slate-200 flex items-center gap-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-100 dark:border-slate-700 rounded-full px-3 py-1">
              <span className={`w-1.5 h-1.5 rounded-full ${isGuest ? "bg-amber-400" : "bg-emerald-500 animate-pulse"}`}></span>
              {isGuest ? "Guest Consultation" : userProfile?.displayName || user?.email?.split("@")[0] || "Health Partner"}
            </span>
          </div>

          <button
            id="nav-logout-button"
            onClick={onLogout}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold border border-slate-200 dark:border-slate-700 hover:border-red-200 text-slate-600 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/20 cursor-pointer transition-all duration-200"
            title="Sign out of HealthSphere AI"
          >
            <LogOut className="w-3.5 h-3.5" />
            <span>Sign Out</span>
          </button>
        </div>

      </div>
    </header>
  );
}
