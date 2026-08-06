import React, { useState } from 'react';
import { 
  Settings, User, Cpu, Bell, Globe, Moon, Sun, 
  Loader2, Save, Terminal, HardDrive, HelpCircle
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { useNotification } from '../context/NotificationContext';
import GlassCard from '../components/GlassCard';

export const SettingsPage: React.FC = () => {
  const { user, updateProfileSettings } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { showToast } = useNotification();

  // Settings State Form
  const [name, setName] = useState(user?.name || '');
  const [targetCareer, setTargetCareer] = useState(user?.targetCareer || '');
  const [language, setLanguage] = useState(user?.language || 'en');
  const [aiProvider, setAiProvider] = useState(() => localStorage.getItem('ai_provider') || 'ollama');
  const [ollamaUrl, setOllamaUrl] = useState(() => localStorage.getItem('ollama_url') || 'http://localhost:11434');
  const [ollamaModel, setOllamaModel] = useState(() => localStorage.getItem('ollama_model') || 'llama3');
  
  const [saving, setSaving] = useState(false);

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      // 1. Update backend user profile
      await updateProfileSettings({
        name,
        targetCareer,
        language
      });

      // 2. Cache local AI settings in LocalStorage for frontend client context if needed
      localStorage.setItem('ai_provider', aiProvider);
      localStorage.setItem('ollama_url', ollamaUrl);
      localStorage.setItem('ollama_model', ollamaModel);

      showToast('System settings updated successfully!', 'success');
    } catch (err) {
      showToast('Could not save settings profile configuration', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-8 animate-fade-in">
      
      {/* Page Header */}
      <div className="border-b border-dark-800/40 pb-6">
        <h2 className="text-3xl font-extrabold font-heading text-dark-50 tracking-tight flex items-center gap-2">
          <Settings className="w-8 h-8 text-primary-400" />
          System Settings
        </h2>
        <p className="text-sm text-dark-400 mt-1">
          Adjust credential details, interface styles, notification systems, and local AMD ROCm AI backends.
        </p>
      </div>

      <form onSubmit={handleSaveSettings} className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        
        {/* Core Profile & Display Configurations (Left) */}
        <div className="lg:col-span-6 flex flex-col gap-6">
          
          {/* Section 1: User Profile */}
          <GlassCard className="flex flex-col gap-4">
            <h3 className="font-heading font-bold text-sm text-dark-100 flex items-center gap-2 border-b border-dark-800/40 pb-3">
              <User className="w-4.5 h-4.5 text-primary-400" />
              Profile Details
            </h3>

            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold text-dark-300">Display Name</label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl border glass-input text-xs"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold text-dark-300">Target Career Path</label>
                <input
                  type="text"
                  required
                  value={targetCareer}
                  onChange={(e) => setTargetCareer(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl border glass-input text-xs"
                />
              </div>
            </div>
          </GlassCard>

          {/* Section 2: Display & Notifications */}
          <GlassCard className="flex flex-col gap-4">
            <h3 className="font-heading font-bold text-sm text-dark-100 flex items-center gap-2 border-b border-dark-800/40 pb-3">
              <Moon className="w-4.5 h-4.5 text-cyan-400" />
              Theme & Interface Styles
            </h3>

            <div className="flex flex-col gap-4">
              {/* Theme toggle option */}
              <div className="flex justify-between items-center py-1">
                <div>
                  <span className="text-xs font-bold text-dark-100 block">Dark Theme Mode</span>
                  <span className="text-[10px] text-dark-400">Reduce eye strain in dark environments</span>
                </div>
                <button
                  type="button"
                  onClick={toggleTheme}
                  className="px-4 py-2 bg-dark-900 border border-dark-800 rounded-xl text-xs font-bold text-dark-200 hover:text-cyan-400 transition-all flex items-center gap-2"
                >
                  {theme === 'dark' ? <Moon className="w-4 h-4 text-cyan-400" /> : <Sun className="w-4 h-4 text-yellow-500" />}
                  Theme: {theme.toUpperCase()}
                </button>
              </div>

              {/* Language Selector */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold text-dark-300 flex items-center gap-1.5">
                  <Globe className="w-4 h-4 text-dark-400" /> Language selection
                </label>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full px-4 py-3 rounded-xl border glass-input text-xs cursor-pointer text-dark-300 bg-dark-950"
                >
                  <option value="en">English (EN)</option>
                  <option value="es">Spanish (ES)</option>
                  <option value="hi">Hindi (HI)</option>
                </select>
              </div>
            </div>
          </GlassCard>

        </div>

        {/* Local AI / ROCm Optimization Configurations (Right) */}
        <div className="lg:col-span-6 flex flex-col gap-6">
          <GlassCard className="flex flex-col gap-4">
            <h3 className="font-heading font-bold text-sm text-dark-100 flex items-center gap-2 border-b border-dark-800/40 pb-3">
              <Cpu className="w-4.5 h-4.5 text-cyan-400" />
              AI Inference Backend Configuration
            </h3>

            <div className="flex flex-col gap-4.5">
              
              {/* Select Provider */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold text-dark-300">AI LLM Provider</label>
                <div className="grid grid-cols-2 gap-4">
                  <div
                    onClick={() => setAiProvider('ollama')}
                    className={`p-3 rounded-xl border cursor-pointer text-center flex flex-col gap-1 transition-all ${
                      aiProvider === 'ollama'
                        ? 'border-cyan-500 bg-cyan-950/20 text-cyan-300'
                        : 'border-dark-800 bg-dark-950/10 text-dark-400 hover:border-dark-700'
                    }`}
                  >
                    <span className="text-xs font-bold font-heading">Local Inference (Ollama)</span>
                    <span className="text-[9px] opacity-75">ROCm accelerated, 100% Free</span>
                  </div>

                  <div
                    onClick={() => setAiProvider('openai')}
                    className={`p-3 rounded-xl border cursor-pointer text-center flex flex-col gap-1 transition-all ${
                      aiProvider === 'openai'
                        ? 'border-cyan-500 bg-cyan-950/20 text-cyan-300'
                        : 'border-dark-800 bg-dark-950/10 text-dark-400 hover:border-dark-700'
                    }`}
                  >
                    <span className="text-xs font-bold font-heading">Cloud API (OpenAI)</span>
                    <span className="text-[9px] opacity-75">Requires cloud keys setup</span>
                  </div>
                </div>
              </div>

              {/* Ollama options */}
              {aiProvider === 'ollama' ? (
                <div className="flex flex-col gap-4 animate-fade-in">
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-bold text-dark-300">Ollama API URL</label>
                    <input
                      type="url"
                      value={ollamaUrl}
                      onChange={(e) => setOllamaUrl(e.target.value)}
                      className="w-full px-4 py-2.5 rounded-xl border glass-input text-xs font-mono"
                    />
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-bold text-dark-300">Downloaded Model Name</label>
                    <select
                      value={ollamaModel}
                      onChange={(e) => setOllamaModel(e.target.value)}
                      className="w-full px-4 py-3 rounded-xl border glass-input text-xs text-dark-300 bg-dark-950"
                    >
                      <option value="llama3">Llama 3 (8B)</option>
                      <option value="qwen2.5">Qwen 2.5 (7B)</option>
                      <option value="phi3">Phi 3 (3.8B)</option>
                      <option value="mistral">Mistral (7B)</option>
                    </select>
                  </div>

                  {/* GPU Hardware Instructions */}
                  <div className="p-4 bg-[#080a10] border border-slate-900 rounded-xl font-mono text-[10px] text-slate-400 leading-relaxed flex flex-col gap-2">
                    <div className="flex items-center gap-1.5 text-cyan-400 font-bold font-sans text-xs">
                      <HardDrive className="w-4 h-4" />
                      <span>AMD ROCm GPU Acceleration Guide</span>
                    </div>
                    <p className="font-sans">To optimize speed, follow these settings on your local AMD rig:</p>
                    <div className="text-cyan-300"># Enforce specific graphics compatibility version</div>
                    <div>$env:HSA_OVERRIDE_GFX_VERSION="10.3.0"</div>
                    <div className="text-cyan-300"># Verify local Ollama server status</div>
                    <div>curl http://localhost:11434/api/tags</div>
                  </div>
                </div>
              ) : (
                <div className="p-4 bg-dark-950/40 border border-dark-800 rounded-xl flex items-start gap-2.5 text-xs text-dark-400 leading-normal animate-fade-in">
                  <HelpCircle className="w-5 h-5 text-primary-400 shrink-0 mt-0.5" />
                  <span>
                    When choosing Cloud API mode, edit the `.env` settings file in your `backend/` root directory to include your custom `OPENAI_API_KEY` configurations.
                  </span>
                </div>
              )}

            </div>
          </GlassCard>

          {/* Submit button */}
          <button
            type="submit"
            disabled={saving}
            className="w-full py-4.5 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl shadow-lg flex items-center justify-center gap-2 text-xs transition-all hover:scale-102 disabled:opacity-60"
          >
            {saving ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Saving Configs...
              </>
            ) : (
              <>
                <Save className="w-4.5 h-4.5" />
                Save System Configurations
              </>
            )}
          </button>
        </div>

      </form>

    </div>
  );
};

export default SettingsPage;
