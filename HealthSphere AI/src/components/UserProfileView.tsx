import React, { useState, useEffect } from "react";
import { User, Mail, Calendar, Activity, MessageSquare, Save, Edit2, ShieldCheck, Heart, Trash2, Sparkles, Clock, AlertCircle } from "lucide-react";
import { getUserProfile, saveUserProfile, getChatSessions, getSymptomChecks, deleteChatSession } from "../lib/firebase";
import { UserProfile, ChatSession, SymptomCheckResult } from "../types";
import { motion } from "motion/react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer
} from "recharts";

// Custom chart tooltip component
const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 p-3 rounded-2xl shadow-md text-left text-xs space-y-1.5">
        <p className="font-bold text-slate-800 dark:text-slate-100">{label}</p>
        {payload.map((entry: any, index: number) => (
          <div key={index} className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
            <span className="text-slate-500 dark:text-slate-400 font-medium">{entry.name}:</span>
            <span className="font-bold text-slate-900 dark:text-white">{entry.value}</span>
          </div>
        ))}
      </div>
    );
  }
  return null;
};

interface UserProfileViewProps {
  user: any;
  isGuest: boolean;
  onProfileUpdate: (profile: UserProfile) => void;
  onNavigateToTab: (tab: string) => void;
}

export default function UserProfileView({ user, isGuest, onProfileUpdate, onNavigateToTab }: UserProfileViewProps) {
  // Local profile state
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Editable fields
  const [displayName, setDisplayName] = useState("");
  const [age, setAge] = useState<number | "">("");
  const [gender, setGender] = useState("");
  const [healthNotes, setHealthNotes] = useState("");

  // History stats
  const [chats, setChats] = useState<ChatSession[]>([]);
  const [checks, setChecks] = useState<SymptomCheckResult[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Load initial profile data and history
  useEffect(() => {
    if (!user) return;
    
    const loadProfileAndHistory = async () => {
      setLoading(true);
      setLoadingHistory(true);
      try {
        // Fetch user profile
        const userProfile = await getUserProfile(user.uid);
        if (userProfile) {
          setProfile(userProfile);
          setDisplayName(userProfile.displayName || "");
          setAge(userProfile.age || "");
          setGender(userProfile.gender || "");
          setHealthNotes(userProfile.healthNotes || "");
        } else {
          // If no profile exists yet, initialize with defaults
          const defaultProfile: UserProfile = {
            uid: user.uid,
            email: user.email,
            displayName: user.displayName || user.email?.split("@")[0] || "Health Partner",
            createdAt: new Date()
          };
          setProfile(defaultProfile);
          setDisplayName(defaultProfile.displayName || "");
        }

        // Fetch user history
        const chatSessions = await getChatSessions(user.uid);
        setChats(chatSessions || []);

        const symptomChecks = await getSymptomChecks(user.uid);
        setChecks(symptomChecks || []);
      } catch (err) {
        console.error("Error loading user profile information:", err);
        setErrorMsg("Failed to load account profile data.");
      } finally {
        setLoading(false);
        setLoadingHistory(false);
      }
    };

    loadProfileAndHistory();
  }, [user]);

  // Handle saving profile changes
  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) return;
    
    setSaveLoading(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    const updatedData: Partial<UserProfile> = {
      displayName: displayName.trim() || null,
      age: age === "" ? undefined : Number(age),
      gender: gender || undefined,
      healthNotes: healthNotes.trim() || undefined
    };

    try {
      await saveUserProfile(user.uid, updatedData);
      
      const fullProfile: UserProfile = {
        uid: user.uid,
        email: user.email,
        displayName: displayName.trim() || null,
        createdAt: profile?.createdAt || new Date(),
        age: age === "" ? undefined : Number(age),
        gender: gender || undefined,
        healthNotes: healthNotes.trim() || undefined
      };
      
      setProfile(fullProfile);
      onProfileUpdate(fullProfile);
      setIsEditing(false);
      setSuccessMsg("Account profile details updated successfully.");
      
      // Clear success message after 3 seconds
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (err) {
      console.error("Failed to save user profile:", err);
      setErrorMsg("Failed to store profile details to Firestore.");
    } finally {
      setSaveLoading(false);
    }
  };

  // Handle deleting chat sessions from within the profile view
  const handleDeleteSession = async (sessionId: string) => {
    if (!user) return;
    if (!window.confirm("Are you sure you want to delete this consultation history?")) return;

    try {
      await deleteChatSession(sessionId);
      setChats(prev => prev.filter(c => c.id !== sessionId));
    } catch (err) {
      console.error("Failed to delete chat session:", err);
    }
  };

  // Helper to get formatted date
  const formatDate = (timestampVal: any) => {
    if (!timestampVal) return "N/A";
    if (timestampVal.toDate) return timestampVal.toDate().toLocaleDateString(undefined, { dateStyle: "medium" });
    if (timestampVal instanceof Date) return timestampVal.toLocaleDateString(undefined, { dateStyle: "medium" });
    const parsed = new Date(timestampVal);
    return isNaN(parsed.getTime()) ? "N/A" : parsed.toLocaleDateString(undefined, { dateStyle: "medium" });
  };

  // Generate dynamic trailing 6 months
  const generateTrailingMonths = () => {
    const data = [];
    const now = new Date();
    for (let i = 5; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const monthLabel = d.toLocaleDateString("en-US", { month: "short" });
      const yearLabel = d.getFullYear().toString().substring(2);
      data.push({
        key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`,
        month: `${monthLabel} '${yearLabel}`,
        symptomChecks: 0,
        chatbotUsage: 0,
        monthIndex: d.getMonth(),
        year: d.getFullYear()
      });
    }
    return data;
  };

  // Prepare combined monthly dataset for Recharts
  const prepareChartData = () => {
    const monthsData = generateTrailingMonths();

    // Fill symptom checks
    checks.forEach((check) => {
      if (!check.createdAt) return;
      let d: Date;
      if ((check.createdAt as any).toDate) {
        d = (check.createdAt as any).toDate();
      } else if (check.createdAt instanceof Date) {
        d = check.createdAt;
      } else {
        d = new Date(check.createdAt);
      }
      if (isNaN(d.getTime())) return;

      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      const match = monthsData.find((m) => m.key === key);
      if (match) {
        match.symptomChecks += 1;
      }
    });

    // Fill chatbot consultations/usage
    chats.forEach((chat) => {
      if (!chat.createdAt) return;
      let d: Date;
      if ((chat.createdAt as any).toDate) {
        d = (chat.createdAt as any).toDate();
      } else if (chat.createdAt instanceof Date) {
        d = chat.createdAt;
      } else {
        d = new Date(chat.createdAt);
      }
      if (isNaN(d.getTime())) return;

      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      const match = monthsData.find((m) => m.key === key);
      if (match) {
        match.chatbotUsage += 1;
      }
    });

    return monthsData;
  };

  if (isGuest) {
    return (
      <div id="profile-guest-fallback" className="max-w-4xl mx-auto space-y-6 text-left">
        <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-3xl p-8 shadow-sm space-y-6 text-center py-12">
          <div className="w-16 h-16 bg-amber-50 dark:bg-amber-950/20 text-amber-500 rounded-full flex items-center justify-center mx-auto border border-amber-100 dark:border-amber-900/40">
            <User className="w-8 h-8" />
          </div>
          <div className="space-y-2 max-w-md mx-auto">
            <h2 className="text-xl font-sans font-bold text-slate-900 dark:text-white">Guest Session Mode</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed font-normal">
              You are currently using HealthSphere AI as a guest. Profiles, personalized triage trackers, and persistent chat consultations are only accessible for registered university and health partners.
            </p>
          </div>
          <div className="pt-2 flex justify-center gap-4">
            <button
              onClick={() => onNavigateToTab("dashboard")}
              className="px-5 py-2.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 font-semibold text-xs uppercase tracking-wider rounded-xl transition cursor-pointer"
            >
              Back to Dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div id="user-profile-layout" className="max-w-5xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-8 text-left">
      
      {/* LEFT COLUMN: Profile Account Card & Editable Details */}
      <div className="lg:col-span-1 space-y-6">
        <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-3xl p-6 shadow-sm">
          
          {/* Avatar and static header */}
          <div className="text-center pb-6 border-b border-slate-50 dark:border-slate-800/60 space-y-3">
            <div className="w-20 h-20 bg-blue-50 dark:bg-blue-950/40 border border-blue-100 dark:border-blue-900 rounded-full flex items-center justify-center mx-auto text-blue-600 dark:text-blue-400 relative">
              <User className="w-10 h-10" />
              <div className="absolute bottom-0 right-0 w-5 h-5 bg-emerald-500 border-2 border-white dark:border-slate-900 rounded-full" title="Active Connection" />
            </div>
            
            <div>
              <h2 className="text-lg font-sans font-extrabold text-slate-900 dark:text-white truncate">
                {profile?.displayName || "Health Partner"}
              </h2>
              <span className="text-xs text-slate-400 dark:text-slate-500 block truncate">{user?.email}</span>
            </div>

            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-blue-50 dark:bg-blue-950/40 border border-blue-100/40 dark:border-blue-900/40 text-[10px] font-bold text-blue-600 dark:text-blue-400 uppercase tracking-wider">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Verified Account</span>
            </div>
          </div>

          {/* Quick system info */}
          <div className="py-4 space-y-3 text-xs text-slate-500 dark:text-slate-400">
            <div className="flex justify-between items-center">
              <span className="font-medium text-slate-400">Member Since:</span>
              <span className="font-semibold text-slate-800 dark:text-slate-200">{formatDate(profile?.createdAt)}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="font-medium text-slate-400">UID Signature:</span>
              <span className="font-mono text-[10px] text-slate-800 dark:text-slate-200 select-all" title={user?.uid}>
                {user?.uid ? `${user.uid.substring(0, 8)}...` : "N/A"}
              </span>
            </div>
          </div>

          {/* Edit/Action triggers */}
          {!isEditing && (
            <button
              id="btn-edit-profile"
              onClick={() => setIsEditing(true)}
              className="w-full mt-4 bg-slate-50 hover:bg-slate-100 dark:bg-slate-800/50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 font-bold text-xs uppercase tracking-wider py-2.5 rounded-xl flex items-center justify-center gap-2 transition cursor-pointer"
            >
              <Edit2 className="w-3.5 h-3.5" />
              <span>Modify Details</span>
            </button>
          )}

        </div>

        {/* Dynamic Alerts Banner */}
        {successMsg && (
          <div className="p-4 bg-emerald-50 dark:bg-emerald-950/25 border border-emerald-100 dark:border-emerald-900/50 rounded-2xl flex items-start gap-3 text-xs text-emerald-800 dark:text-emerald-400">
            <ShieldCheck className="w-4.5 h-4.5 text-emerald-500 shrink-0 mt-0.5" />
            <p className="font-medium leading-relaxed">{successMsg}</p>
          </div>
        )}

        {errorMsg && (
          <div className="p-4 bg-red-50 dark:bg-red-950/25 border border-red-100 dark:border-red-900/50 rounded-2xl flex items-start gap-3 text-xs text-red-800 dark:text-red-400">
            <AlertCircle className="w-4.5 h-4.5 text-red-500 shrink-0 mt-0.5" />
            <p className="font-medium leading-relaxed">{errorMsg}</p>
          </div>
        )}
      </div>

      {/* RIGHT COLUMN: Interactive Form OR Clinical Bio & History timelines */}
      <div className="lg:col-span-2 space-y-6">
        
        {/* Profile Modification Form / General Health Information Details */}
        {isEditing ? (
          <form onSubmit={handleSave} className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-5">
            <div className="border-b border-slate-50 dark:border-slate-800 pb-3">
              <h3 className="text-base font-sans font-bold text-slate-900 dark:text-white">Modify Personal Health Details</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">Updating these details helps contextualize disease library materials and general recommendations.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="block text-[11px] font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider">Display Name</label>
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="e.g. John Doe"
                  maxLength={50}
                  className="w-full px-4 py-2 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 focus:border-blue-500 dark:focus:border-blue-500 focus:bg-white dark:focus:bg-slate-900 rounded-xl text-sm font-medium transition-all duration-200 outline-none text-slate-800 dark:text-slate-100"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="block text-[11px] font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider">Age (Years)</label>
                  <input
                    type="number"
                    value={age}
                    onChange={(e) => setAge(e.target.value === "" ? "" : Number(e.target.value))}
                    placeholder="e.g. 25"
                    min={0}
                    max={120}
                    className="w-full px-4 py-2 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 focus:border-blue-500 dark:focus:border-blue-500 focus:bg-white dark:focus:bg-slate-900 rounded-xl text-sm font-medium transition-all duration-200 outline-none text-slate-800 dark:text-slate-100"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="block text-[11px] font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider">Gender</label>
                  <select
                    value={gender}
                    onChange={(e) => setGender(e.target.value)}
                    className="w-full px-4 py-2 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 focus:border-blue-500 dark:focus:border-blue-500 focus:bg-white dark:focus:bg-slate-900 rounded-xl text-sm font-medium transition-all duration-200 outline-none text-slate-800 dark:text-slate-100 cursor-pointer"
                  >
                    <option value="">Select...</option>
                    <option value="Male">Male</option>
                    <option value="Female">Female</option>
                    <option value="Other">Other</option>
                    <option value="Prefer not to say">Prefer not to say</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="block text-[11px] font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider">Important Health Notes</label>
              <textarea
                value={healthNotes}
                onChange={(e) => setHealthNotes(e.target.value)}
                placeholder="List allergies, chronic conditions, or general wellness details..."
                rows={3}
                className="w-full px-4 py-2 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 focus:border-blue-500 dark:focus:border-blue-500 focus:bg-white dark:focus:bg-slate-900 rounded-xl text-sm font-medium transition-all duration-200 outline-none text-slate-800 dark:text-slate-100 resize-none"
              />
            </div>

            <div className="pt-2 border-t border-slate-50 dark:border-slate-800/60 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setIsEditing(false)}
                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-400 font-bold text-xs uppercase tracking-wider rounded-xl transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saveLoading}
                className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs uppercase tracking-wider rounded-xl flex items-center gap-1.5 transition cursor-pointer shadow-sm disabled:bg-slate-200 disabled:text-slate-400"
              >
                <Save className="w-4 h-4" />
                <span>{saveLoading ? "Saving..." : "Save Details"}</span>
              </button>
            </div>
          </form>
        ) : (
          <>
            {/* Profile Clinical Summary Box */}
            <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-4">
              <div className="flex items-center gap-2 border-b border-slate-50 dark:border-slate-800 pb-3">
                <Heart className="w-5 h-5 text-blue-600" />
                <h3 className="font-sans font-bold text-slate-900 dark:text-white uppercase tracking-wider text-sm">Personal Triage Dossier</h3>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="bg-slate-50 dark:bg-slate-950/40 p-3 rounded-xl border border-slate-100/50 dark:border-slate-800/40">
                  <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">Age</span>
                  <span className="block text-sm font-bold text-slate-800 dark:text-slate-200 mt-1">{profile?.age ? `${profile.age} Years` : "Not specified"}</span>
                </div>
                <div className="bg-slate-50 dark:bg-slate-950/40 p-3 rounded-xl border border-slate-100/50 dark:border-slate-800/40">
                  <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">Gender</span>
                  <span className="block text-sm font-bold text-slate-800 dark:text-slate-200 mt-1">{profile?.gender || "Not specified"}</span>
                </div>
                <div className="bg-slate-50 dark:bg-slate-950/40 p-3 rounded-xl border border-slate-100/50 dark:border-slate-800/40">
                  <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">Triage Status</span>
                  <span className="block text-sm font-bold text-emerald-600 dark:text-emerald-400 mt-1 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse"></span>
                    Active Triage
                  </span>
                </div>
              </div>

              <div className="space-y-1 bg-slate-50 dark:bg-slate-950/40 p-4 border border-slate-100/50 dark:border-slate-800/40 rounded-2xl text-left">
                <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">Health Notes & Advisory Alerts</span>
                <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed font-normal mt-1 whitespace-pre-line">
                  {profile?.healthNotes || "No clinical observations or allergies logged. Click \"Modify Details\" above to save allergies, chronic diseases, or medical profiles to custom-tailor triage advisory suggestions."}
                </p>
              </div>
            </div>

            {/* MONTHLY ACTIVITY CHART CARD */}
            <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-4">
              <div className="flex items-center justify-between border-b border-slate-50 dark:border-slate-800 pb-3">
                <div className="flex items-center gap-2">
                  <Activity className="w-5 h-5 text-blue-600" />
                  <h3 className="font-sans font-bold text-slate-900 dark:text-white uppercase tracking-wider text-sm">Monthly Engagement Trends</h3>
                </div>
                <span className="text-[10px] bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 px-2 py-0.5 rounded-full font-bold uppercase tracking-wider">
                  Last 6 Months
                </span>
              </div>

              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={prepareChartData()} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorChecks" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#2563eb" stopOpacity={0.2}/>
                        <stop offset="95%" stopColor="#2563eb" stopOpacity={0}/>
                      </linearGradient>
                      <linearGradient id="colorChats" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.2}/>
                        <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" className="dark:stroke-slate-800/50" />
                    <XAxis 
                      dataKey="month" 
                      tickLine={false} 
                      axisLine={false} 
                      tick={{ fill: '#94a3b8', fontSize: 10, fontWeight: 500 }} 
                    />
                    <YAxis 
                      tickLine={false} 
                      axisLine={false} 
                      tick={{ fill: '#94a3b8', fontSize: 10, fontWeight: 500 }} 
                      allowDecimals={false}
                    />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend 
                      verticalAlign="top" 
                      height={36} 
                      iconType="circle"
                      iconSize={8}
                      wrapperStyle={{ fontSize: 11, fontWeight: 600 }}
                    />
                    <Area 
                      type="monotone" 
                      name="Symptom Checks" 
                      dataKey="symptomChecks" 
                      stroke="#2563eb" 
                      strokeWidth={2}
                      fillOpacity={1} 
                      fill="url(#colorChecks)" 
                    />
                    <Area 
                      type="monotone" 
                      name="AI Chatbot" 
                      dataKey="chatbotUsage" 
                      stroke="#10b981" 
                      strokeWidth={2}
                      fillOpacity={1} 
                      fill="url(#colorChats)" 
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          </>
        )}

        {/* COMBINED INTERACTIVE HISTORY SECTION */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          
          {/* Recent Symptom Triage Checks */}
          <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-3xl p-5 shadow-sm space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-50 dark:border-slate-800/60 pb-3">
              <Activity className="w-4.5 h-4.5 text-blue-600" />
              <h3 className="font-sans font-bold text-slate-900 dark:text-white uppercase tracking-wider text-xs">Recent Triage Reports</h3>
            </div>

            <div className="space-y-2.5 max-h-[350px] overflow-y-auto pr-1">
              {loadingHistory ? (
                <div className="text-center py-6">
                  <span className="text-xs text-slate-400">Loading triage logs...</span>
                </div>
              ) : checks.length === 0 ? (
                <div className="text-center py-8 bg-slate-50 dark:bg-slate-950/30 border border-slate-100/50 dark:border-slate-800/50 rounded-2xl text-slate-400">
                  <span className="text-xs font-semibold block">No Triage Reports</span>
                  <button
                    onClick={() => onNavigateToTab("symptom-checker")}
                    className="mt-2 text-[10px] font-bold text-blue-600 dark:text-blue-400 uppercase tracking-wider hover:underline"
                  >
                    Run Symptom Checker
                  </button>
                </div>
              ) : (
                checks.map((check) => (
                  <div
                    key={check.id}
                    className="p-3 bg-slate-50 dark:bg-slate-950/20 border border-slate-100 dark:border-slate-800/50 rounded-xl space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[9px] font-mono text-slate-400">{formatDate(check.createdAt)}</span>
                      <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider border ${
                        check.riskLevel === "High"
                          ? "bg-rose-50 dark:bg-rose-950/25 border-rose-100 dark:border-rose-900/40 text-rose-600 dark:text-rose-400"
                          : check.riskLevel === "Moderate"
                          ? "bg-amber-50 dark:bg-amber-950/25 border-amber-100 dark:border-amber-900/40 text-amber-600 dark:text-amber-400"
                          : "bg-emerald-50 dark:bg-emerald-950/25 border-emerald-100 dark:border-emerald-900/40 text-emerald-600 dark:text-emerald-400"
                      }`}>
                        {check.riskLevel} Risk
                      </span>
                    </div>

                    <div className="space-y-1">
                      <span className="text-xs font-bold text-slate-800 dark:text-slate-200 block truncate">{check.conditions.join(" / ")}</span>
                      <div className="flex flex-wrap gap-1">
                        {check.symptoms.map((s, idx) => (
                          <span key={idx} className="text-[9px] bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 text-slate-500 dark:text-slate-400 px-1 py-0.5 rounded">
                            {s.replace(/(\(.*?\))/g, "").trim()}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Recent Chat Consultations */}
          <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-3xl p-5 shadow-sm space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-50 dark:border-slate-800/60 pb-3">
              <MessageSquare className="w-4.5 h-4.5 text-blue-600" />
              <h3 className="font-sans font-bold text-slate-900 dark:text-white uppercase tracking-wider text-xs">Consultation History</h3>
            </div>

            <div className="space-y-2.5 max-h-[350px] overflow-y-auto pr-1">
              {loadingHistory ? (
                <div className="text-center py-6">
                  <span className="text-xs text-slate-400">Loading consultations...</span>
                </div>
              ) : chats.length === 0 ? (
                <div className="text-center py-8 bg-slate-50 dark:bg-slate-950/30 border border-slate-100/50 dark:border-slate-800/50 rounded-2xl text-slate-400">
                  <span className="text-xs font-semibold block">No Chat Records</span>
                  <button
                    onClick={() => onNavigateToTab("chatbot")}
                    className="mt-2 text-[10px] font-bold text-blue-600 dark:text-blue-400 uppercase tracking-wider hover:underline"
                  >
                    Start consultation
                  </button>
                </div>
              ) : (
                chats.map((chat) => (
                  <div
                    key={chat.id}
                    className="p-3 bg-slate-50 dark:bg-slate-950/20 border border-slate-100 dark:border-slate-800/50 rounded-xl flex items-center justify-between group transition-all"
                  >
                    <div className="space-y-1 overflow-hidden mr-2">
                      <span className="text-[9px] font-mono text-slate-400 block">{formatDate(chat.createdAt)}</span>
                      <span
                        onClick={() => onNavigateToTab("chatbot")}
                        className="text-xs font-bold text-slate-800 dark:text-slate-200 block truncate hover:text-blue-600 dark:hover:text-blue-400 cursor-pointer"
                        title="Open consultation in Assistant"
                      >
                        {chat.title}
                      </span>
                      <span className="text-[10px] text-slate-400 block">{chat.messages?.length || 0} messages</span>
                    </div>

                    <button
                      onClick={() => handleDeleteSession(chat.id)}
                      className="p-1.5 text-slate-400 hover:text-red-500 dark:hover:text-red-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                      title="Delete chat log"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

        </div>

      </div>

    </div>
  );
}
