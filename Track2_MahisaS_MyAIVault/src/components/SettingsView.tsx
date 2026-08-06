import React, { useState } from 'react';
import {
  Settings,
  User,
  ShieldCheck,
  Download,
  RefreshCw,
  Trash2,
  Lock,
  CheckCircle2,
  AlertCircle,
  Save,
} from 'lucide-react';
import { UserProfile, DocumentItem } from '../types';

interface SettingsViewProps {
  user: UserProfile;
  documents: DocumentItem[];
  onUpdateProfile: (updated: Partial<UserProfile>) => void;
  onResetData: () => void;
}

export const SettingsView: React.FC<SettingsViewProps> = ({
  user,
  documents,
  onUpdateProfile,
  onResetData,
}) => {
  const [name, setName] = useState(user.name);
  const [email, setEmail] = useState(user.email);
  const [university, setUniversity] = useState(user.university);
  const [targetRole, setTargetRole] = useState(user.targetRole);
  const [bio, setBio] = useState(user.bio);
  const [saved, setSaved] = useState(false);
  const [showClearModal, setShowClearModal] = useState(false);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    onUpdateProfile({ name, email, university, targetRole, bio });
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const handleExportData = () => {
    const dataStr = JSON.stringify({ user, documents, exportedAt: new Date().toISOString() }, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `MyAI_Vault_Export_${user.name.replace(/\s+/g, '_')}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="p-4 lg:p-8 space-y-8 max-w-4xl mx-auto text-white">
      {/* Header */}
      <div className="border-b border-white/10 pb-6">
        <h1 className="text-2xl font-bold text-white flex items-center space-x-3">
          <Settings className="w-6 h-6 text-sky-400" />
          <span>Vault Settings & Profile</span>
        </h1>
        <p className="text-xs text-slate-400 mt-1">Manage user identity credentials, export vault backup, and system preferences.</p>
      </div>

      {/* Profile Settings Form */}
      <form onSubmit={handleSave} className="p-6 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-white/10 pb-4">
          <h2 className="text-base font-bold text-white flex items-center space-x-2">
            <User className="w-4 h-4 text-sky-400" />
            <span>Digital Identity Profile</span>
          </h2>
          {saved && (
            <span className="text-xs text-emerald-400 font-mono flex items-center space-x-1">
              <CheckCircle2 className="w-4 h-4" />
              <span>Saved Successfully</span>
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div>
            <label className="block text-slate-300 font-medium mb-1">Full Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full bg-slate-900 border border-white/10 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-sky-400"
            />
          </div>

          <div>
            <label className="block text-slate-300 font-medium mb-1">Email Address</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-slate-900 border border-white/10 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-sky-400"
            />
          </div>

          <div>
            <label className="block text-slate-300 font-medium mb-1">University / Institution</label>
            <input
              type="text"
              value={university}
              onChange={(e) => setUniversity(e.target.value)}
              className="w-full bg-slate-900 border border-white/10 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-sky-400"
            />
          </div>

          <div>
            <label className="block text-slate-300 font-medium mb-1">Target Career Goal</label>
            <input
              type="text"
              value={targetRole}
              onChange={(e) => setTargetRole(e.target.value)}
              className="w-full bg-slate-900 border border-white/10 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-sky-400"
            />
          </div>

          <div className="sm:col-span-2">
            <label className="block text-slate-300 font-medium mb-1">Professional Bio</label>
            <textarea
              rows={3}
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              className="w-full bg-slate-900 border border-white/10 rounded-xl p-3 text-xs text-white focus:outline-none focus:border-sky-400"
            />
          </div>
        </div>

        <div className="flex justify-end pt-2">
          <button
            type="submit"
            className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-white font-semibold text-xs shadow-md shadow-sky-500/20 flex items-center space-x-2"
          >
            <Save className="w-4 h-4" />
            <span>Save Identity Changes</span>
          </button>
        </div>
      </form>

      {/* AI Key & Security Status Box */}
      <div className="p-6 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-4 shadow-xl">
        <h2 className="text-base font-bold text-white flex items-center space-x-2 border-b border-white/10 pb-4">
          <Lock className="w-4 h-4 text-sky-400" />
          <span>Security & AI Configuration</span>
        </h2>

        <div className="p-4 rounded-xl bg-slate-900/80 border border-white/5 text-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-slate-300 font-semibold">Gemini API Key Integration:</span>
            <span className="px-2.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-mono font-bold text-[10px]">
              Server-Side Active
            </span>
          </div>
          <p className="text-slate-400 text-[11px] leading-relaxed">
            Your Gemini API key is managed securely on the server via the AI Studio Secrets panel.
          </p>
        </div>
      </div>

      {/* Data Operations */}
      <div className="p-6 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-4 shadow-xl">
        <h2 className="text-base font-bold text-white flex items-center space-x-2 border-b border-white/10 pb-4">
          <Download className="w-4 h-4 text-sky-400" />
          <span>Vault Data Backup & Management</span>
        </h2>

        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 text-xs">
          <div>
            <strong className="text-white block font-semibold">Export Vault Metadata (JSON)</strong>
            <p className="text-slate-400 text-[11px]">Download all extracted documents, skills, and graph links.</p>
          </div>

          <button
            onClick={handleExportData}
            className="px-5 py-2.5 rounded-xl bg-white/10 hover:bg-white/15 text-slate-200 text-xs font-semibold flex items-center space-x-2 shrink-0 border border-white/10 transition-colors"
          >
            <Download className="w-4 h-4 text-sky-400" />
            <span>Export JSON Backup</span>
          </button>
        </div>

        <div className="border-t border-white/10 pt-4 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs">
          <div>
            <strong className="text-white block font-semibold">Reset to Sample Student Vault</strong>
            <p className="text-slate-400 text-[11px]">Restores the initial sample documents for Stanford Senior Alex Morgan.</p>
          </div>

          <button
            onClick={onResetData}
            className="px-5 py-2.5 rounded-xl bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 text-xs font-semibold flex items-center space-x-2 shrink-0 border border-indigo-500/30 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            <span>Reset Vault Data</span>
          </button>
        </div>
      </div>
    </div>
  );
};
