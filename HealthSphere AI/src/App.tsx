import React, { useState, useEffect } from "react";
import { onAuthStateChanged, signOut, User } from "firebase/auth";
import { auth, getUserProfile, getChatSessions, getSymptomChecks } from "./lib/firebase";
import { UserProfile } from "./types";
import Navbar from "./components/Navbar";
import Login from "./components/Login";
import DiseaseLibrary from "./components/DiseaseLibrary";
import SymptomChecker from "./components/SymptomChecker";
import AIChatbot from "./components/AIChatbot";
import HealthTips from "./components/HealthTips";
import EmergencyHospitals from "./components/EmergencyHospitals";
import UserProfileView from "./components/UserProfileView";
import { 
  Heart, Sparkles, BookOpen, Activity, AlertTriangle, 
  ShieldCheck, ArrowRight, User as UserIcon, Calendar, CheckSquare, MessageSquare, BookOpenCheck 
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

export default function App() {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<User | null>(null);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [isGuest, setIsGuest] = useState(false);
  const [currentTab, setCurrentTab] = useState("dashboard");

  // Dark mode state with standard persistence
  const [darkMode, setDarkMode] = useState<boolean>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("healthsphere-theme");
      if (saved) return saved === "dark";
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    }
    return false;
  });

  // Sync dark class on document element
  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add("dark");
      localStorage.setItem("healthsphere-theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("healthsphere-theme", "light");
    }
  }, [darkMode]);

  const toggleDarkMode = () => setDarkMode(prev => !prev);

  // Dashboard stats
  const [chatsCount, setChatsCount] = useState(0);
  const [checksCount, setChecksCount] = useState(0);

  useEffect(() => {
    // Listener for Auth changes
    // Listener for Auth changes
    const unsubscribe = onAuthStateChanged(auth, (firebaseUser) => {
      if (firebaseUser) {
        setUser(firebaseUser);
        setIsGuest(false);
        
        // Load data in the background to prevent hanging if Firestore is offline/unprovisioned
        getUserProfile(firebaseUser.uid).then((profile) => {
          if (profile) setUserProfile(profile);
        }).catch((err) => {
          console.error("Error loading user profile:", err);
        });

        getChatSessions(firebaseUser.uid).then((chats) => {
          if (chats) setChatsCount(chats.length);
        }).catch((err) => {
          console.error("Error loading chats count:", err);
        });

        getSymptomChecks(firebaseUser.uid).then((checks) => {
          if (checks) setChecksCount(checks.length);
        }).catch((err) => {
          console.error("Error loading checks count:", err);
        });
      } else {
        setUser(null);
        setUserProfile(null);
      }
      
      // Delay loading screen just slightly to feel highly polished
      setTimeout(() => {
        setLoading(false);
      }, 1500);
    });

    return () => unsubscribe();
  }, []);

  // Synchronize dashboard counts reactively whenever currentTab changes to dashboard or user changes
  useEffect(() => {
    if (user && currentTab === "dashboard") {
      const syncCounts = async () => {
        try {
          const chats = await getChatSessions(user.uid);
          setChatsCount(chats.length);
          const checks = await getSymptomChecks(user.uid);
          setChecksCount(checks.length);
        } catch (err) {
          console.error("Error refreshing dashboard counts:", err);
        }
      };
      syncCounts();
    }
  }, [user, currentTab]);

  const handleLoginSuccess = async (loggedInUser: User | null, guestMode: boolean) => {
    if (guestMode) {
      setIsGuest(true);
      setUser(null);
      setUserProfile(null);
      setCurrentTab("dashboard");
    } else if (loggedInUser) {
      setUser(loggedInUser);
      setIsGuest(false);
      setCurrentTab("dashboard");
      try {
        const profile = await getUserProfile(loggedInUser.uid);
        setUserProfile(profile);
        const chats = await getChatSessions(loggedInUser.uid);
        setChatsCount(chats.length);
        const checks = await getSymptomChecks(loggedInUser.uid);
        setChecksCount(checks.length);
      } catch (err) {
        console.error(err);
      }
    }
  };

  const handleLogout = async () => {
    try {
      await signOut(auth);
      setUser(null);
      setUserProfile(null);
      setIsGuest(false);
      setCurrentTab("dashboard");
    } catch (err) {
      console.error("Logout failed:", err);
    }
  };

  // 1. Loading Splash Screen
  if (loading) {
    return (
      <div id="splash-loading-screen" className="min-h-screen bg-slate-900 flex flex-col items-center justify-center text-white font-sans">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5 }}
          className="text-center space-y-6"
        >
          {/* Pulsing professional Logo */}
          <div className="w-16 h-16 bg-blue-600 rounded-2xl flex items-center justify-center mx-auto shadow-xl shadow-blue-500/20 animate-pulse">
            <svg className="w-10 h-10 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <rect x="5" y="5" width="14" height="14" rx="4" />
              <path d="M12 8v8M8 12h8" />
              <circle cx="18" cy="6" r="1.5" fill="currentColor" className="text-emerald-400" />
            </svg>
          </div>

          <div className="space-y-1.5">
            <h1 className="text-3xl font-bold tracking-tight font-sans">
              HealthSphere <span className="text-blue-500">AI</span>
            </h1>
            <span className="text-xs font-mono tracking-wider text-slate-400 uppercase font-semibold">
              Intelligent Public Health Assistant
            </span>
          </div>

          <div className="w-48 h-[3px] bg-slate-800 rounded-full mx-auto overflow-hidden relative">
            <div className="h-full bg-blue-500 rounded-full w-24 absolute left-0 animate-[loading-bar_1.5s_infinite_ease-in-out]"></div>
          </div>
          
          <span className="text-[10px] text-slate-500 font-mono block">
            Initializing AI consultation secure environments...
          </span>
        </motion.div>
      </div>
    );
  }

  // 2. Auth Guard Gate (Show Login Screen)
  if (!user && !isGuest) {
    return <Login onLoginSuccess={handleLoginSuccess} darkMode={darkMode} toggleDarkMode={toggleDarkMode} />;
  }

  // 3. Authenticated App Frame
  return (
    <div id="healthsphere-root" className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 text-slate-800 dark:text-slate-100 font-sans flex flex-col justify-between transition-colors duration-300">
      
      {/* Dynamic Header / Navbar with Dark Mode Toggle */}
      <Navbar 
        currentTab={currentTab} 
        setTab={setCurrentTab} 
        user={user} 
        userProfile={userProfile}
        isGuest={isGuest} 
        onLogout={handleLogout}
        darkMode={darkMode}
        toggleDarkMode={toggleDarkMode}
      />

      {/* Main Content Area */}
      <main id="app-main-content" className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full space-y-12">
        <AnimatePresence mode="wait">
          
          {/* TAB: DASHBOARD */}
          {currentTab === "dashboard" && (
            <motion.div
              key="dashboard"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="space-y-8"
            >
              {/* Dynamic Welcome Hero Section */}
              <div className="bg-gradient-to-r from-blue-900 to-slate-900 text-white rounded-3xl p-8 md:p-12 shadow-xl relative overflow-hidden">
                <div className="absolute right-0 top-0 bottom-0 w-1/3 opacity-10 hidden md:block">
                  {/* Decorative medical lines */}
                  <svg className="w-full h-full text-white" viewBox="0 0 100 100" preserveAspectRatio="none">
                    <path d="M0,50 Q25,20 50,50 T100,50" fill="none" stroke="currentColor" strokeWidth="2" />
                    <path d="M0,70 Q25,40 50,70 T100,70" fill="none" stroke="currentColor" strokeWidth="1" />
                  </svg>
                </div>

                <div className="max-w-2xl space-y-6 relative z-10 text-left">
                  <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-500/20 border border-blue-400/20 text-xs font-semibold text-blue-300">
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>Welcome to HealthSphere AI Portal</span>
                  </div>

                  <h1 className="text-3xl md:text-4xl font-bold tracking-tight font-sans leading-tight">
                    {isGuest 
                      ? "Guest Triage Consultation" 
                      : `Hello, ${userProfile?.displayName || user?.email?.split("@")[0] || "Health Partner"}`}
                  </h1>
                  
                  <p className="text-sm text-slate-300 font-normal leading-relaxed">
                    Helping communities make safe, evidence-based public health decisions. Triage symptoms, explore official disease guides, and request professional AI medical awareness assistance.
                  </p>

                  <div className="pt-2 flex flex-wrap gap-4">
                    <button
                      id="hero-btn-consult"
                      onClick={() => setCurrentTab("chatbot")}
                      className="px-6 py-3 bg-blue-600 hover:bg-blue-700 active:scale-95 text-white font-bold text-xs uppercase tracking-wider rounded-xl shadow-md shadow-blue-500/10 flex items-center gap-2 transition cursor-pointer"
                    >
                      <span>Start AI Consultation</span>
                      <ArrowRight className="w-4 h-4" />
                    </button>
                    <button
                      id="hero-btn-triage"
                      onClick={() => setCurrentTab("symptom-checker")}
                      className="px-6 py-3 bg-white/10 hover:bg-white/20 active:scale-95 text-white font-bold text-xs uppercase tracking-wider rounded-xl border border-white/20 flex items-center gap-2 transition cursor-pointer"
                    >
                      <Activity className="w-4 h-4" />
                      <span>Run Symptom Triage</span>
                    </button>
                  </div>
                </div>
              </div>

              {/* Connected Clinical Metrics (Stats Bar) */}
              {!isGuest && (
                <div id="clinical-metrics" className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-2xl p-5 shadow-sm flex items-center gap-4 text-left">
                    <div className="w-12 h-12 rounded-xl bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 flex items-center justify-center shrink-0 border border-blue-100 dark:border-blue-900">
                      <MessageSquare className="w-6 h-6" />
                    </div>
                    <div>
                      <span className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest block font-bold">Saved Consultations</span>
                      <span className="text-xl font-sans font-extrabold text-slate-950 dark:text-white mt-0.5 block">{chatsCount} Sessions</span>
                    </div>
                  </div>

                  <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-2xl p-5 shadow-sm flex items-center gap-4 text-left">
                    <div className="w-12 h-12 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0 border border-emerald-100 dark:border-emerald-900">
                      <BookOpenCheck className="w-6 h-6" />
                    </div>
                    <div>
                      <span className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest block font-bold">Symptom Checks Completed</span>
                      <span className="text-xl font-sans font-extrabold text-slate-950 dark:text-white mt-0.5 block">{checksCount} Reports</span>
                    </div>
                  </div>

                  <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-2xl p-5 shadow-sm flex items-center gap-4 text-left">
                    <div className="w-12 h-12 rounded-xl bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 flex items-center justify-center shrink-0 border border-indigo-100 dark:border-indigo-900">
                      <ShieldCheck className="w-6 h-6" />
                    </div>
                    <div>
                      <span className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest block font-bold">Profile Security Status</span>
                      <span className="text-xl font-sans font-extrabold text-slate-950 dark:text-white mt-0.5 block">Firebase Active</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Quick Actions Bento Grid */}
              <div id="dashboard-bento" className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {/* Panel 1: Disease library teaser */}
                <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-3xl p-6 shadow-sm flex flex-col justify-between text-left">
                  <div className="space-y-3">
                    <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 border border-blue-100 dark:border-blue-900 flex items-center justify-center">
                      <BookOpen className="w-5 h-5" />
                    </div>
                    <h3 className="text-base font-sans font-bold text-slate-900 dark:text-white tracking-tight">Clinical Disease Library</h3>
                    <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed font-normal">
                      Explore detailed medical entries for Dengue, Flu, COVID, Diabetes, Asthma, and Heart Disease. Learn symptoms,causes, and prevention checklists.
                    </p>
                  </div>
                  <button
                    id="teaser-btn-diseases"
                    onClick={() => setCurrentTab("diseases")}
                    className="mt-6 text-xs font-bold text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 flex items-center gap-1 uppercase tracking-wider cursor-pointer"
                  >
                    <span>Browse Library</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>

                {/* Panel 2: Emergency directories teaser */}
                <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-3xl p-6 shadow-sm flex flex-col justify-between text-left">
                  <div className="space-y-3">
                    <div className="w-10 h-10 rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-600 dark:text-rose-400 border border-rose-100 dark:border-rose-900 flex items-center justify-center">
                      <AlertTriangle className="w-5 h-5" />
                    </div>
                    <h3 className="text-base font-sans font-bold text-slate-900 dark:text-white tracking-tight">Emergency Helplines & Directory</h3>
                    <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed font-normal">
                      Instant access to universal dispatches, public helplines, disease outbreak reporting centers, and local clinical hospital networks.
                    </p>
                  </div>
                  <button
                    id="teaser-btn-emergency"
                    onClick={() => setCurrentTab("emergency")}
                    className="mt-6 text-xs font-bold text-rose-600 dark:text-rose-400 hover:text-rose-700 dark:hover:text-rose-300 flex items-center gap-1 uppercase tracking-wider cursor-pointer"
                  >
                    <span>View Emergency Numbers</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Health Tips of the Day Component (Renders inside home dashboard as requested) */}
              <HealthTips />
            </motion.div>
          )}

          {/* TAB: DISEASE LIBRARY */}
          {currentTab === "diseases" && (
            <motion.div
              key="diseases"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
            >
              <DiseaseLibrary />
            </motion.div>
          )}

          {/* TAB: AI CHATBOT */}
          {currentTab === "chatbot" && (
            <motion.div
              key="chatbot"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
            >
              <AIChatbot user={user} isGuest={isGuest} />
            </motion.div>
          )}

          {/* TAB: SYMPTOM CHECKER */}
          {currentTab === "symptom-checker" && (
            <motion.div
              key="symptom-checker"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
            >
              <SymptomChecker user={user} isGuest={isGuest} />
            </motion.div>
          )}

          {/* TAB: EMERGENCY & DIRECTORY */}
          {currentTab === "emergency" && (
            <motion.div
              key="emergency"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
            >
              <EmergencyHospitals />
            </motion.div>
          )}

          {/* TAB: USER PROFILE */}
          {currentTab === "profile" && (
            <motion.div
              key="profile"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
            >
              <UserProfileView 
                user={user} 
                isGuest={isGuest} 
                onProfileUpdate={(updatedProfile) => setUserProfile(updatedProfile)}
                onNavigateToTab={(tab) => setCurrentTab(tab)}
              />
            </motion.div>
          )}

          {/* TAB: ABOUT (Information about the website and portal purpose) */}
          {currentTab === "about" && (
            <motion.div
              key="about"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="space-y-8 max-w-4xl mx-auto text-left"
            >
              <div className="bg-white p-8 border border-slate-100 rounded-3xl shadow-sm space-y-6">
                
                <div className="border-b border-slate-100 pb-4">
                  <h2 className="text-2xl font-sans font-bold tracking-tight text-slate-900">
                    About HealthSphere AI Portal
                  </h2>
                  <p className="text-xs text-slate-500 mt-1">
                    Your Intelligent Public Health Education & Community Support Companion
                  </p>
                </div>

                {/* Section: Website Overview */}
                <div className="space-y-3">
                  <p className="text-sm text-slate-600 leading-relaxed font-normal">
                    Welcome to <strong>HealthSphere AI</strong>, a comprehensive digital public health portal dedicated to raising disease awareness, encouraging preventive healthcare habits, and offering interactive educational support for individuals and communities.
                  </p>
                  <p className="text-sm text-slate-600 leading-relaxed font-normal">
                    This website serves as a reliable, user-friendly hub designed to bridge the gap between complex health data and clear, actionable public wellness insights. By providing accessible resources, we empower users to take proactive charge of their safety and physical well-being.
                  </p>
                </div>

                {/* Section: Key Website Features */}
                <div className="space-y-4 pt-4 border-t border-slate-50">
                  <h3 className="text-base font-sans font-bold text-slate-900 tracking-tight">Key Website Features</h3>
                  
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="space-y-1.5 p-4 bg-slate-50/50 border border-slate-100 rounded-2xl">
                      <div className="font-semibold text-xs uppercase tracking-wider text-blue-600 font-mono">01. Clinical Disease Library</div>
                      <p className="text-xs text-slate-600 leading-relaxed">
                        An indexed catalog of common infectious diseases (e.g., Dengue, Influenza, COVID-19) and critical chronic conditions (e.g., Diabetes, Heart Health). Learn about early warning signs, risk factors, transmission routes, and scientifically-backed wellness checklists.
                      </p>
                    </div>

                    <div className="space-y-1.5 p-4 bg-slate-50/50 border border-slate-100 rounded-2xl">
                      <div className="font-semibold text-xs uppercase tracking-wider text-blue-600 font-mono">02. Interactive Symptom Triage</div>
                      <p className="text-xs text-slate-600 leading-relaxed">
                        A personalized symptom checker questionnaire designed to assess general symptom presentations. It provides high-level risk classifications (Mild, Moderate, High Risk) and recommends appropriate non-prescriptive, self-care guidelines or clinical intervention steps.
                      </p>
                    </div>

                    <div className="space-y-1.5 p-4 bg-slate-50/50 border border-slate-100 rounded-2xl">
                      <div className="font-semibold text-xs uppercase tracking-wider text-blue-600 font-mono">03. Interactive AI Health Assistant</div>
                      <p className="text-xs text-slate-600 leading-relaxed">
                        Powered by secure artificial intelligence models, our chat assistant offers instant informational guidance regarding general wellness, nutrition habits, vaccination plans, disease prevention tips, and hygiene practices.
                      </p>
                    </div>

                    <div className="space-y-1.5 p-4 bg-slate-50/50 border border-slate-100 rounded-2xl">
                      <div className="font-semibold text-xs uppercase tracking-wider text-blue-600 font-mono">04. Hotlines & Clinic Directory</div>
                      <p className="text-xs text-slate-600 leading-relaxed">
                        A centralized directory detailing vital emergency health contacts, regional public health hotlines, specialized clinics, and clinical trauma facilities to ensure you have quick guidance to physical resources when needed.
                      </p>
                    </div>
                  </div>
                </div>

                {/* Section: Our Purpose */}
                <div className="space-y-3 pt-4 border-t border-slate-50">
                  <h3 className="text-base font-sans font-bold text-slate-900 tracking-tight">Our Core Purpose</h3>
                  <p className="text-xs text-slate-600 leading-relaxed font-normal">
                    HealthSphere AI aims to foster an informed public. We believe that preventative action is the strongest medicine. Through modern, accessible, and intuitive visual tools, this website encourages routine hand hygiene, timely vaccination schedules, balanced dietary plans, active lifestyle habits, and general mental health well-being.
                  </p>
                </div>

                {/* Safe Disclaimer Alert */}
                <div className="p-4 bg-amber-50 border border-amber-100 rounded-2xl space-y-2 text-xs text-amber-950">
                  <span className="font-bold uppercase tracking-widest block flex items-center gap-1 text-amber-800">
                    <ShieldCheck className="w-4.5 h-4.5 text-amber-600" />
                    <span>Important Health Advisory & Disclaimer</span>
                  </span>
                  <p className="leading-relaxed font-normal text-amber-800">
                    This website is built solely for educational purposes, public awareness, and interactive guidance. The resources, symptom trackers, and AI advisor do not constitute professional clinical diagnostics, medical prescriptions, or clinical treatment plans. Always consult a certified healthcare professional or licensed physician for any official medical diagnoses or treatment recommendations.
                  </p>
                </div>

              </div>
            </motion.div>
          )}

        </AnimatePresence>
      </main>

      {/* Styled Professional Footer */}
      <footer id="app-footer-bar" className="w-full bg-slate-900 text-slate-400 text-[11px] py-6 border-t border-slate-800 mt-12 text-left">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <rect x="5" y="5" width="14" height="14" rx="4" />
              <path d="M12 8v8M8 12h8" />
            </svg>
            <span className="font-semibold text-slate-300">HealthSphere AI • Public Health Assistant</span>
          </div>
          <div className="flex gap-4">
            <button onClick={() => setCurrentTab("about")} className="hover:text-white transition">About HealthSphere AI</button>
          </div>
        </div>
      </footer>

    </div>
  );
}
