import React from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  ArrowRight, FileText, Sparkles, Users, Map, Cpu, ShieldCheck, 
  ChevronRight, Play, Terminal, HelpCircle, HardDrive
} from 'lucide-react';

export const LandingPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen text-slate-100 relative">
      
      {/* Top Background Glow Blobs */}
      <div className="absolute top-[-10%] left-[-10%] w-[500px] h-[500px] rounded-full bg-primary-600/10 blur-[120px] pointer-events-none" />
      <div className="absolute top-[20%] right-[-10%] w-[600px] h-[600px] rounded-full bg-cyan-500/10 blur-[130px] pointer-events-none" />

      {/* HEADER NAVBAR */}
      <header className="max-w-7xl mx-auto px-6 h-20 flex items-center justify-between relative z-10">
        <div className="flex items-center gap-3 cursor-pointer" onClick={() => navigate('/')}>
          <div className="w-10 h-10 bg-gradient-to-tr from-primary-600 to-cyan-500 rounded-xl flex items-center justify-center text-white font-bold shadow-lg">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="6">
              <path d="M50 15 L58 42 L85 50 L58 58 L50 85 L42 58 L15 50 L42 42 Z" fill="currentColor"/>
            </svg>
          </div>
          <span className="font-extrabold text-xl tracking-tight bg-gradient-to-r from-white to-slate-300 bg-clip-text text-transparent font-heading">
            CareerPilot <span className="bg-gradient-to-r from-primary-400 to-cyan-400 bg-clip-text text-transparent">AI</span>
          </span>
        </div>

        <div className="flex items-center gap-4">
          <button 
            onClick={() => navigate('/login')}
            className="px-4 py-2 text-sm font-semibold text-slate-300 hover:text-white transition-colors"
          >
            Sign In
          </button>
          <button
            onClick={() => navigate('/signup')}
            className="px-5 py-2.5 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white text-sm font-bold rounded-xl shadow-lg shadow-primary-500/10 hover:shadow-primary-500/20 transition-all hover:scale-102"
          >
            Get Started
          </button>
        </div>
      </header>

      {/* HERO SECTION */}
      <section className="max-w-7xl mx-auto px-6 pt-16 pb-20 relative z-10 flex flex-col items-center text-center">
        
        {/* Hackathon Badge */}
        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-dark-900/50 border border-primary-500/30 text-primary-300 text-xs font-bold mb-6 tracking-wide shadow-inner animate-float">
          <Cpu className="w-4 h-4 text-cyan-400 animate-spin-slow" />
          <span>AMD AI DevMaster Hackathon Submission</span>
        </div>

        <h1 className="text-4xl md:text-7xl font-extrabold tracking-tight font-heading max-w-4xl leading-[1.1] mb-6">
          Navigate Your Career Trajectory with <span className="bg-gradient-to-r from-primary-400 via-purple-400 to-cyan-400 bg-clip-text text-transparent text-glow-purple">Autonomous AI</span>
        </h1>

        <p className="text-base md:text-xl text-slate-400 max-w-2xl leading-relaxed mb-10">
          Supercharge your interview prep, audit your resume against ATS criteria, map out your curriculum gaps, and consult an intelligent placement mentor—powered by local 
          <span className="text-cyan-400 font-bold"> AMD ROCm GPU acceleration</span>.
        </p>

        {/* Call to Actions */}
        <div className="flex flex-col sm:flex-row gap-4 mb-16">
          <button
            onClick={() => navigate('/signup')}
            className="px-8 py-4 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl shadow-xl shadow-primary-500/20 hover:shadow-primary-500/30 flex items-center justify-center gap-2.5 transition-all hover:scale-103 group"
          >
            Launch CareerPilot
            <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
          </button>
          
          <button
            onClick={() => {
              const el = document.getElementById('amd-section');
              if (el) el.scrollIntoView({ behavior: 'smooth' });
            }}
            className="px-8 py-4 bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 text-slate-300 font-semibold rounded-xl flex items-center justify-center gap-2 transition-all hover:scale-102"
          >
            <HardDrive className="w-5 h-5 text-cyan-400" />
            AMD GPU Setup
          </button>
        </div>

        {/* UI Mockup Placeholder Card */}
        <div className="w-full max-w-5xl rounded-2xl p-1 bg-gradient-to-br from-primary-500/20 via-purple-500/10 to-cyan-500/20 border border-slate-800 shadow-2xl relative">
          <div className="absolute inset-0 rounded-2xl bg-gradient-to-tr from-primary-500/10 to-cyan-500/10 filter blur-xl opacity-50 -z-10" />
          <div className="bg-slate-950 rounded-xl overflow-hidden aspect-[16/9] border border-slate-800/40 relative flex items-center justify-center">
            
            {/* SVG Illustration of App Dashboard */}
            <svg viewBox="0 0 800 450" className="w-full h-full opacity-85" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect width="800" height="450" fill="#0b0f19" />
              {/* Sidebar */}
              <rect x="0" y="0" width="180" height="450" fill="#080a10" opacity="0.8" />
              <circle cx="35" cy="35" r="10" fill="#8b5cf6" />
              <rect x="55" y="30" width="80" height="10" rx="4" fill="#1e293b" />
              
              <rect x="20" y="80" width="140" height="28" rx="6" fill="#8b5cf6" fillOpacity="0.1" stroke="#8b5cf6" strokeOpacity="0.3" />
              <rect x="35" y="89" width="10" height="10" fill="#8b5cf6" rx="2" />
              <rect x="55" y="89" width="80" height="8" rx="3" fill="#8b5cf6" />

              <rect x="35" y="130" width="10" height="10" fill="#475569" rx="2" />
              <rect x="55" y="131" width="80" height="8" rx="3" fill="#334155" />

              <rect x="35" y="170" width="10" height="10" fill="#475569" rx="2" />
              <rect x="55" y="171" width="80" height="8" rx="3" fill="#334155" />

              {/* Main panel */}
              <rect x="210" y="30" width="160" height="90" rx="10" fill="#111827" stroke="#1f2937" />
              <circle cx="250" cy="75" r="22" fill="#10b981" fillOpacity="0.1" stroke="#10b981" strokeWidth="4" strokeDasharray="100 38" />
              <text x="242" y="79" fill="#10b981" fontSize="12" fontWeight="bold" fontFamily="sans-serif">85</text>
              <rect x="290" y="55" width="60" height="10" rx="3" fill="#fff" opacity="0.9" />
              <rect x="290" y="75" width="40" height="7" rx="3" fill="#475569" />

              <rect x="390" y="30" width="160" height="90" rx="10" fill="#111827" stroke="#1f2937" />
              <circle cx="430" cy="75" r="22" fill="#8b5cf6" fillOpacity="0.1" stroke="#8b5cf6" strokeWidth="4" strokeDasharray="110 20" />
              <text x="420" y="79" fill="#8b5cf6" fontSize="12" fontWeight="bold" fontFamily="sans-serif">9.0</text>
              <rect x="470" y="55" width="60" height="10" rx="3" fill="#fff" opacity="0.9" />
              <rect x="470" y="75" width="45" height="7" rx="3" fill="#475569" />

              <rect x="570" y="30" width="200" height="90" rx="10" fill="#111827" stroke="#1f2937" />
              <rect x="590" y="50" width="100" height="10" rx="3" fill="#fff" opacity="0.9" />
              <rect x="590" y="70" width="150" height="7" rx="3" fill="#1e293b" />
              <rect x="590" y="85" width="110" height="7" rx="3" fill="#1e293b" />

              {/* Chart representation */}
              <rect x="210" y="145" width="340" height="180" rx="10" fill="#111827" stroke="#1f2937" />
              <path d="M 230 280 L 280 250 L 330 260 L 380 210 L 430 230 L 480 180 L 520 190" stroke="url(#paint-grad)" strokeWidth="4" fill="none" />
              <path d="M 230 280 L 280 250 L 330 260 L 380 210 L 430 230 L 480 180 L 520 190 L 520 295 L 230 295 Z" fill="url(#paint-area-grad)" opacity="0.15" />
              <line x1="230" y1="295" x2="520" y2="295" stroke="#334155" strokeWidth="2" />
              
              {/* Roadmap representation */}
              <rect x="570" y="145" width="200" height="275" rx="10" fill="#111827" stroke="#1f2937" />
              <rect x="590" y="165" width="100" height="12" rx="4" fill="#8b5cf6" />
              <circle cx="600" cy="210" r="8" fill="#10b981" />
              <rect x="620" y="206" width="120" height="8" rx="3" fill="#334155" />
              <circle cx="600" cy="245" r="8" fill="#10b981" />
              <rect x="620" y="241" width="120" height="8" rx="3" fill="#334155" />
              <circle cx="600" cy="280" r="8" fill="#1e293b" stroke="#475569" />
              <rect x="620" y="276" width="100" height="8" rx="3" fill="#1e293b" />
              
              {/* Bottom activity log */}
              <rect x="210" y="340" width="340" height="80" rx="10" fill="#111827" stroke="#1f2937" />
              <circle cx="240" cy="380" r="18" fill="#312e81" />
              <rect x="270" y="370" width="120" height="8" rx="3" fill="#fff" />
              <rect x="270" y="385" width="200" height="6" rx="3" fill="#475569" />

              <defs>
                <linearGradient id="paint-grad" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#8b5cf6" />
                  <stop offset="100%" stopColor="#06b6d4" />
                </linearGradient>
                <linearGradient id="paint-area-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#8b5cf6" stopOpacity="1" />
                  <stop offset="100%" stopColor="#8b5cf6" stopOpacity="0" />
                </linearGradient>
              </defs>
            </svg>
            <div className="absolute inset-0 bg-slate-950/20 backdrop-blur-[1px] hover:backdrop-blur-0 flex items-center justify-center transition-all cursor-pointer group" onClick={() => navigate('/signup')}>
              <div className="w-16 h-16 rounded-full bg-white/10 group-hover:bg-primary-600/90 border border-white/20 flex items-center justify-center transition-all shadow-xl group-hover:scale-110">
                <Play className="w-6 h-6 fill-white text-white translate-x-0.5" />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CORE FEATURES GRID */}
      <section className="max-w-7xl mx-auto px-6 py-24 border-t border-slate-900 relative z-10">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-5xl font-extrabold font-heading mb-4">Complete Suite of AI Career Tools</h2>
          <p className="text-slate-400 max-w-2xl mx-auto">Everything you need to bypass placement struggles and land your dream job role.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
          
          <div className="p-8 rounded-2xl bg-slate-950 border border-slate-900 hover:border-primary-500/30 transition-all hover:-translate-y-1">
            <div className="w-12 h-12 bg-primary-500/10 rounded-xl flex items-center justify-center text-primary-400 mb-6">
              <FileText className="w-6 h-6" />
            </div>
            <h3 className="text-lg font-bold font-heading mb-3">ATS Resume Critic</h3>
            <p className="text-sm text-slate-400 leading-relaxed">Upload your PDF resume to extract content, analyze missing keywords, score readability, and generate improved metrics bullet points.</p>
          </div>

          <div className="p-8 rounded-2xl bg-slate-950 border border-slate-900 hover:border-purple-500/30 transition-all hover:-translate-y-1">
            <div className="w-12 h-12 bg-purple-500/10 rounded-xl flex items-center justify-center text-purple-400 mb-6">
              <Users className="w-6 h-6" />
            </div>
            <h3 className="text-lg font-bold font-heading mb-3">Voice Mock Interview</h3>
            <p className="text-sm text-slate-400 leading-relaxed">Conduce mock HR or Technical interviews. Speak replies into your mic and listen to AI speak questions back, receiving granular score diagnostics.</p>
          </div>

          <div className="p-8 rounded-2xl bg-slate-950 border border-slate-900 hover:border-cyan-500/30 transition-all hover:-translate-y-1">
            <div className="w-12 h-12 bg-cyan-500/10 rounded-xl flex items-center justify-center text-cyan-400 mb-6">
              <Sparkles className="w-6 h-6" />
            </div>
            <h3 className="text-lg font-bold font-heading mb-3">Skill Gap Assessment</h3>
            <p className="text-sm text-slate-400 leading-relaxed">Contrast your current technologies list against target careers to calculate gap requirements, weekly goals, and approximate completion times.</p>
          </div>

          <div className="p-8 rounded-2xl bg-slate-950 border border-slate-900 hover:border-indigo-500/30 transition-all hover:-translate-y-1">
            <div className="w-12 h-12 bg-indigo-500/10 rounded-xl flex items-center justify-center text-indigo-400 mb-6">
              <Map className="w-6 h-6" />
            </div>
            <h3 className="text-lg font-bold font-heading mb-3">Learning Roadmaps</h3>
            <p className="text-sm text-slate-400 leading-relaxed">Generate 4-week interactive timelines matching missing competencies. Tick off tasks on your dashboard calendar to audit progress rates.</p>
          </div>

        </div>
      </section>

      {/* AMD ROCM HARDWARE SECTION */}
      <section id="amd-section" className="max-w-7xl mx-auto px-6 py-20 border-t border-slate-900 relative z-10">
        <div className="rounded-3xl bg-slate-950 border border-cyan-500/20 p-8 md:p-12 relative overflow-hidden">
          {/* Background decoration */}
          <div className="absolute right-0 top-0 w-80 h-80 rounded-full bg-cyan-500/5 blur-3xl -z-10" />
          
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
            <div className="lg:col-span-7 flex flex-col gap-6">
              <div className="flex items-center gap-2 text-cyan-400 font-bold text-xs uppercase tracking-wider">
                <Cpu className="w-5 h-5 animate-pulse" />
                <span>AMD Radeon™ Optimized Local Inference</span>
              </div>
              <h2 className="text-3xl md:text-5xl font-extrabold font-heading">Run AI Free Locally on ROCm™</h2>
              <p className="text-slate-400 leading-relaxed text-sm md:text-base">
                CareerPilot AI is built with local inference support. If you have an AMD Radeon GPU, you can leverage 
                <strong> ROCm (Radeon Open Compute)</strong> to run LLMs locally via Ollama with full GPU hardware acceleration. 
                This gives you absolute privacy, offline operations, and zero cloud API subscription costs.
              </p>
              
              <div className="flex flex-col sm:flex-row gap-4 mt-2">
                <div className="flex items-center gap-3">
                  <ShieldCheck className="w-5 h-5 text-emerald-400 shrink-0" />
                  <span className="text-xs font-semibold text-slate-300">100% Secure Local Memory Data</span>
                </div>
                <div className="flex items-center gap-3">
                  <ShieldCheck className="w-5 h-5 text-emerald-400 shrink-0" />
                  <span className="text-xs font-semibold text-slate-300">Fast Token Generation (AMD ROCm)</span>
                </div>
              </div>
            </div>

            <div className="lg:col-span-5">
              <div className="p-6 rounded-2xl bg-[#080a10] border border-slate-900 font-mono text-xs text-slate-300">
                <div className="flex items-center justify-between border-b border-slate-900 pb-2 mb-3">
                  <span className="text-[10px] text-slate-500">AMD Local GPU Accelerator Script</span>
                  <div className="flex gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
                    <span className="w-2.5 h-2.5 rounded-full bg-yellow-500" />
                    <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                  </div>
                </div>
                <div className="flex flex-col gap-2">
                  <div className="text-slate-500"># Set ROCm environment overrides on Windows</div>
                  <div className="text-cyan-400">$env:HSA_OVERRIDE_GFX_VERSION="10.3.0"</div>
                  <div className="text-slate-500"># Run Ollama local inference server</div>
                  <div className="text-primary-400">ollama run llama3</div>
                  <div className="text-slate-500"># Start CareerPilot AI backend in ROCm mode</div>
                  <div className="text-emerald-400">npm run dev</div>
                  <div className="text-slate-400 mt-2 p-1.5 rounded bg-dark-900 border border-slate-800 text-[10px] flex items-center gap-2">
                    <Terminal className="w-4 h-4 text-cyan-400" />
                    <span>Backend connects to http://localhost:11434</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* PRICING PLANS SECTION */}
      <section className="max-w-7xl mx-auto px-6 py-20 border-t border-slate-900 relative z-10">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-5xl font-extrabold font-heading mb-4">Pricing Tailored for Everyone</h2>
          <p className="text-slate-400 max-w-2xl mx-auto">Access placement guidance without paying premium fees.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-5xl mx-auto">
          
          {/* Plan 1 */}
          <div className="p-8 rounded-2xl bg-slate-950 border border-slate-900 flex flex-col gap-6 relative">
            <div>
              <h3 className="font-heading font-extrabold text-xl mb-1">Local Host Mode</h3>
              <p className="text-xs text-slate-400">Run local models on your own GPU</p>
            </div>
            <div className="flex items-baseline gap-1.5 font-heading">
              <span className="text-4xl font-extrabold">$0</span>
              <span className="text-xs text-slate-400">/ forever</span>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">Perfect for AMD Radeon card owners who want free local GPU acceleration using Ollama/ROCm.</p>
            <ul className="flex-1 flex flex-col gap-3 text-xs text-slate-300 border-t border-slate-900 pt-4">
              <li className="flex items-center gap-2">
                <ChevronRight className="w-4 h-4 text-cyan-400" /> Unlimited Local AI Chats
              </li>
              <li className="flex items-center gap-2">
                <ChevronRight className="w-4 h-4 text-cyan-400" /> Free PDF Resume Analysis
              </li>
              <li className="flex items-center gap-2">
                <ChevronRight className="w-4 h-4 text-cyan-400" /> Voice Mock Interviews
              </li>
              <li className="flex items-center gap-2">
                <ChevronRight className="w-4 h-4 text-cyan-400" /> Learning Roadmap timelines
              </li>
            </ul>
            <button
              onClick={() => navigate('/signup')}
              className="w-full py-3 bg-slate-900 border border-slate-800 text-slate-300 font-bold rounded-xl text-xs hover:bg-slate-800 transition-all"
            >
              Sign Up Free
            </button>
          </div>

          {/* Plan 2 */}
          <div className="p-8 rounded-2xl bg-slate-950 border-2 border-primary-500/40 flex flex-col gap-6 relative shadow-lg shadow-primary-500/5">
            <div className="absolute top-4 right-4 bg-primary-600/20 text-primary-300 px-2.5 py-0.5 rounded-full text-[10px] font-bold border border-primary-500/20 uppercase tracking-wider">
              Popular
            </div>
            <div>
              <h3 className="font-heading font-extrabold text-xl mb-1">Standard Pro</h3>
              <p className="text-xs text-slate-400">Cloud-assisted smart advisor</p>
            </div>
            <div className="flex items-baseline gap-1.5 font-heading">
              <span className="text-4xl font-extrabold">$9</span>
              <span className="text-xs text-slate-400">/ month</span>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">Ideal for job seekers wanting zero-setup cloud server model support (OpenAI integration).</p>
            <ul className="flex-1 flex flex-col gap-3 text-xs text-slate-300 border-t border-slate-900 pt-4">
              <li className="flex items-center gap-2">
                <ChevronRight className="w-4 h-4 text-primary-400" /> High-speed GPT-4o-mini cloud API
              </li>
              <li className="flex items-center gap-2">
                <ChevronRight className="w-4 h-4 text-primary-400" /> Comprehensive ATS Scoring checklist
              </li>
              <li className="flex items-center gap-2">
                <ChevronRight className="w-4 h-4 text-primary-400" /> Voice input mock interviews
              </li>
              <li className="flex items-center gap-2">
                <ChevronRight className="w-4 h-4 text-primary-400" /> Daily learning track schedule
              </li>
            </ul>
            <button
              onClick={() => navigate('/signup')}
              className="w-full py-3 bg-gradient-to-r from-primary-600 to-cyan-600 text-white font-bold rounded-xl text-xs hover:from-primary-500 hover:to-cyan-500 shadow-md shadow-primary-500/10 transition-all hover:scale-102"
            >
              Get Started Pro
            </button>
          </div>

          {/* Plan 3 */}
          <div className="p-8 rounded-2xl bg-slate-950 border border-slate-900 flex flex-col gap-6 relative">
            <div>
              <h3 className="font-heading font-extrabold text-xl mb-1">College Placement</h3>
              <p className="text-xs text-slate-400">Dedicated campus deployment</p>
            </div>
            <div className="flex items-baseline gap-1.5 font-heading">
              <span className="text-4xl font-extrabold">Custom</span>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">Ideal for universities wanting to deploy custom-branded placement testing environments.</p>
            <ul className="flex-1 flex flex-col gap-3 text-xs text-slate-300 border-t border-slate-900 pt-4">
              <li className="flex items-center gap-2">
                <ChevronRight className="w-4 h-4 text-cyan-400" /> Shared student aggregate analytics
              </li>
              <li className="flex items-center gap-2">
                <ChevronRight className="w-4 h-4 text-cyan-400" /> Campus placement coordinator logs
              </li>
              <li className="flex items-center gap-2">
                <ChevronRight className="w-4 h-4 text-cyan-400" /> Dedicated local servers integration
              </li>
              <li className="flex items-center gap-2">
                <ChevronRight className="w-4 h-4 text-cyan-400" /> 24/7 priority support channels
              </li>
            </ul>
            <button
              onClick={() => navigate('/signup')}
              className="w-full py-3 bg-slate-900 border border-slate-800 text-slate-300 font-bold rounded-xl text-xs hover:bg-slate-800 transition-all"
            >
              Contact Institutions
            </button>
          </div>

        </div>
      </section>

      {/* FOOTER */}
      <footer className="bg-slate-950 border-t border-slate-900 py-12 text-center text-xs text-slate-500 relative z-10">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-primary-600 rounded-lg flex items-center justify-center text-white font-bold">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="6">
                <path d="M50 15 L58 42 L85 50 L58 58 L50 85 L42 58 L15 50 L42 42 Z" fill="currentColor"/>
              </svg>
            </div>
            <span className="font-bold text-slate-300 font-heading">CareerPilot AI</span>
          </div>
          <div className="flex gap-4">
            <span className="hover:text-slate-400 cursor-pointer">Privacy Policy</span>
            <span>•</span>
            <span className="hover:text-slate-400 cursor-pointer">Terms of Service</span>
            <span>•</span>
            <span className="hover:text-slate-400 cursor-pointer">Hackathon Rules</span>
          </div>
          <p>© 2026 CareerPilot AI. Built for the AMD AI DevMaster Hackathon.</p>
        </div>
      </footer>

    </div>
  );
};

export default LandingPage;
