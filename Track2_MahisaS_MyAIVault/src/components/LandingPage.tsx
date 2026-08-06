import React, { useState } from 'react';
import {
  Sparkles,
  Bot,
  Network,
  Search,
  Clock,
  TrendingUp,
  FileText,
  Award,
  Briefcase,
  Code,
  GraduationCap,
  ChevronRight,
  ShieldCheck,
  Zap,
  Play,
  X,
  CheckCircle2,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

interface LandingPageProps {
  onGetStarted: () => void;
  onLogin: () => void;
}

export const LandingPage: React.FC<LandingPageProps> = ({ onGetStarted, onLogin }) => {
  const [showDemoModal, setShowDemoModal] = useState(false);
  const [activeFaq, setActiveFaq] = useState<number | null>(null);

  const featureCards = [
    {
      icon: <Bot className="w-6 h-6 text-sky-400" />,
      title: 'AI Document Understanding',
      description:
        'Upload PDFs, DOCX, Certificates, or Resumes. OCR and NLP extract text, skills, dates, and issuing institutions automatically.',
    },
    {
      icon: <Network className="w-6 h-6 text-sky-400" />,
      title: 'Interactive Knowledge Graph',
      description:
        'Visually connect your credentials to skills, capstone projects, internships, and target career goals in a dynamic node web.',
    },
    {
      icon: <Search className="w-6 h-6 text-sky-400" />,
      title: 'Semantic Vector Search',
      description:
        'Query your vault naturally. Ask "Show all Python certificates" or "Show latest resume" using AI vector similarity search.',
    },
    {
      icon: <TrendingUp className="w-6 h-6 text-sky-400" />,
      title: 'Career & ATS Insights',
      description:
        'Get an instant ATS resume score, identify missing high-demand industry skills, and receive step-by-step learning roadmaps.',
    },
    {
      icon: <Clock className="w-6 h-6 text-sky-400" />,
      title: 'Digital Journey Timeline',
      description:
        'Watch your academic evolution unfold in a sleek vertical timeline from your first coursework to verified industry internships.',
    },
    {
      icon: <Sparkles className="w-6 h-6 text-sky-400" />,
      title: 'RAG Chat Assistant',
      description:
        'A dedicated AI co-pilot that answers recruiters or your own career queries grounded strictly on your verified vault documents.',
    },
  ];

  const faqs = [
    {
      q: 'How is MyAI Vault different from standard cloud storage like Drive or Dropbox?',
      a: 'MyAI Vault is an intelligent digital identity engine. Instead of dumping files in folders, it parses document text using OCR and Gemini NLP, indexes vector embeddings, maps skills to a Knowledge Graph, calculates your ATS score, and allows RAG conversational Q&A over your entire journey.',
    },
    {
      q: 'What document formats are supported?',
      a: 'MyAI Vault supports PDF, Microsoft Word (.docx), Images (.png, .jpg), and compressed archives (.zip) containing certificates or code samples.',
    },
    {
      q: 'Is my data secure and private?',
      a: 'Yes! Your documents are encrypted and indexed strictly inside your isolated user vault. AI processing operates server-side using secure endpoints.',
    },
    {
      q: 'How does the Knowledge Graph connect my documents?',
      a: 'When you upload a document (e.g. Stanford Python Cert), our AI pipeline extracts skills (Python, PyTorch) and automatically links them to related projects (Banking Risk Engine), internships (Goldman Sachs), and career goals.',
    },
  ];

  return (
    <div className="min-h-screen bg-[#071326] text-white overflow-x-hidden selection:bg-sky-500 selection:text-white">
      {/* Background Animated Glows & Particles */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0">
        <div className="absolute top-[-10%] left-[20%] w-[500px] h-[500px] bg-sky-500/10 rounded-full blur-[140px]" />
        <div className="absolute top-[40%] right-[-10%] w-[600px] h-[600px] bg-blue-600/10 rounded-full blur-[160px]" />
        <div className="absolute bottom-[-10%] left-[10%] w-[500px] h-[500px] bg-indigo-500/10 rounded-full blur-[150px]" />
        {/* Particle Grid Lines */}
        <div
          className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: `radial-gradient(#4F9DFF 1px, transparent 1px)`,
            backgroundSize: '32px 32px',
          }}
        />
      </div>

      {/* Header / Navigation */}
      <header className="relative z-10 max-w-7xl mx-auto px-6 py-6 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-600 via-sky-500 to-indigo-400 p-[1px] flex items-center justify-center shadow-lg shadow-sky-500/20">
            <div className="w-full h-full bg-[#0B1F3A] rounded-[11px] flex items-center justify-center">
              <Bot className="w-5 h-5 text-sky-400" />
            </div>
          </div>
          <div>
            <span className="text-xl font-bold tracking-tight bg-gradient-to-r from-white via-slate-100 to-sky-300 bg-clip-text text-transparent">
              MyAI Vault
            </span>
            <span className="block text-[10px] text-sky-400/80 font-mono font-medium -mt-1 tracking-wider uppercase">
              Digital Identity System
            </span>
          </div>
        </div>

        <div className="flex items-center space-x-4">
          <button
            onClick={onLogin}
            className="text-sm font-medium text-slate-300 hover:text-white transition-colors px-4 py-2 rounded-lg hover:bg-white/5"
          >
            Sign In
          </button>
          <button
            onClick={onGetStarted}
            className="text-sm font-semibold text-white bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 px-5 py-2.5 rounded-xl shadow-lg shadow-sky-500/25 transition-all duration-200 transform hover:-translate-y-0.5"
          >
            Get Started Free
          </button>
        </div>
      </header>

      {/* Hero Section */}
      <section className="relative z-10 max-w-5xl mx-auto px-6 pt-16 pb-20 text-center">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <div className="inline-flex items-center space-x-2 px-3.5 py-1.5 rounded-full bg-sky-500/10 border border-sky-400/20 text-sky-300 text-xs font-medium mb-6 backdrop-blur-md">
            <Sparkles className="w-3.5 h-3.5 text-sky-400 animate-pulse" />
            <span>Next-Gen AI Memory & Digital Identity for Career Growth</span>
          </div>

          <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight text-white leading-[1.15] mb-6">
            Your Journey.{' '}
            <span className="bg-gradient-to-r from-sky-400 via-blue-400 to-indigo-300 bg-clip-text text-transparent">
              Understood by AI.
            </span>
          </h1>

          <p className="text-lg sm:text-xl text-slate-300 max-w-2xl mx-auto leading-relaxed mb-10 font-normal">
            An AI-powered Digital Identity System that intelligently parses, connects, organizes, and retrieves
            your academic and professional milestones. Not cloud storage — your personal AI career co-pilot.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-14">
            <button
              onClick={onGetStarted}
              className="w-full sm:w-auto px-8 py-4 rounded-xl bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-white font-semibold text-base shadow-xl shadow-sky-500/30 transition-all transform hover:-translate-y-0.5 flex items-center justify-center space-x-2 group"
            >
              <span>Explore Your AI Vault</span>
              <ChevronRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </button>

            <button
              onClick={() => setShowDemoModal(true)}
              className="w-full sm:w-auto px-7 py-4 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-slate-200 hover:text-white font-medium text-base backdrop-blur-md transition-all flex items-center justify-center space-x-2"
            >
              <Play className="w-4 h-4 text-sky-400 fill-sky-400" />
              <span>Watch Live Demo</span>
            </button>
          </div>

          {/* Interactive Hero Preview Graphic / Glass Card */}
          <div className="relative mx-auto max-w-4xl rounded-2xl bg-slate-900/80 border border-white/10 p-4 sm:p-6 shadow-2xl backdrop-blur-xl overflow-hidden">
            <div className="flex items-center justify-between pb-4 border-b border-white/10 mb-6 text-xs text-slate-400">
              <div className="flex items-center space-x-2">
                <span className="w-3 h-3 rounded-full bg-red-500/80 inline-block" />
                <span className="w-3 h-3 rounded-full bg-yellow-500/80 inline-block" />
                <span className="w-3 h-3 rounded-full bg-green-500/80 inline-block" />
                <span className="ml-2 font-mono text-slate-300">MyAI Vault — Student Identity System</span>
              </div>
              <div className="flex items-center space-x-2 bg-sky-500/10 text-sky-300 px-2.5 py-1 rounded-md border border-sky-500/20">
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>Verified AI Sync Active</span>
              </div>
            </div>

            {/* Interactive Graph Node Chain Teaser */}
            <div className="grid grid-cols-1 md:grid-cols-5 gap-3 text-left mb-4">
              {[
                { label: 'Stanford Python Cert', type: 'Certificate', icon: <Award className="w-4 h-4 text-sky-400" /> },
                { label: 'Python & PyTorch', type: 'Extracted Skill', icon: <Code className="w-4 h-4 text-indigo-400" /> },
                { label: 'Banking Risk AI', type: 'Capstone Project', icon: <FileText className="w-4 h-4 text-blue-400" /> },
                { label: 'Goldman Sachs Intern', type: 'Work Experience', icon: <Briefcase className="w-4 h-4 text-teal-400" /> },
                { label: 'AI/ML Engineer', type: 'Target Goal', icon: <GraduationCap className="w-4 h-4 text-purple-400" /> },
              ].map((step, idx) => (
                <div
                  key={idx}
                  className="p-3.5 rounded-xl bg-white/[0.03] border border-white/10 hover:border-sky-500/40 transition-all relative group"
                >
                  <div className="flex items-center space-x-2 mb-2">
                    {step.icon}
                    <span className="text-[10px] font-mono text-sky-300 uppercase tracking-wider">{step.type}</span>
                  </div>
                  <p className="text-xs font-semibold text-white group-hover:text-sky-300 transition-colors">
                    {step.label}
                  </p>
                  {idx < 4 && (
                    <div className="hidden md:block absolute -right-3 top-1/2 -translate-y-1/2 z-20 text-sky-400/50">
                      →
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="p-3 bg-sky-500/5 rounded-xl border border-sky-500/15 flex items-center justify-between text-xs text-slate-300">
              <div className="flex items-center space-x-2">
                <Bot className="w-4 h-4 text-sky-400 animate-spin" />
                <span>
                  <strong>AI RAG Query:</strong> "How does my Banking Risk project relate to my Goldman Sachs offer?"
                </span>
              </div>
              <span className="text-sky-400 font-mono font-medium">98% Match</span>
            </div>
          </div>
        </motion.div>
      </section>

      {/* Live Impact Metrics */}
      <section className="relative z-10 border-y border-white/10 bg-slate-900/50 backdrop-blur-md py-10">
        <div className="max-w-6xl mx-auto px-6 grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
          {[
            { metric: '24+', label: 'Projects Understood & Indexed' },
            { metric: '18+', label: 'Certificates Verified & Mapped' },
            { metric: '45+', label: 'Unique Technical Skills Tagged' },
            { metric: '98%', label: 'RAG Semantic Accuracy' },
          ].map((item, index) => (
            <div key={index} className="space-y-1">
              <div className="text-3xl sm:text-4xl font-extrabold text-white font-mono bg-gradient-to-r from-sky-400 to-blue-400 bg-clip-text text-transparent">
                {item.metric}
              </div>
              <div className="text-xs sm:text-sm text-slate-400 font-medium">{item.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Core Capabilities Feature Grid */}
      <section className="relative z-10 max-w-6xl mx-auto px-6 py-24">
        <div className="text-center mb-16">
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
            Designed for Modern Academic & Career Excellence
          </h2>
          <p className="text-slate-400 max-w-xl mx-auto text-base">
            Everything students and fresh graduates need to organize credentials, boost ATS resumes, and converse with an AI career memory system.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {featureCards.map((card, idx) => (
            <motion.div
              key={idx}
              whileHover={{ y: -4 }}
              className="p-6 rounded-2xl bg-slate-900/60 border border-white/10 hover:border-sky-500/40 transition-all backdrop-blur-md group"
            >
              <div className="w-12 h-12 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center mb-5 group-hover:bg-sky-500/20 transition-colors">
                {card.icon}
              </div>
              <h3 className="text-lg font-bold text-white mb-2 group-hover:text-sky-300 transition-colors">
                {card.title}
              </h3>
              <p className="text-sm text-slate-300 leading-relaxed">{card.description}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* FAQ Accordion */}
      <section className="relative z-10 max-w-4xl mx-auto px-6 py-16">
        <div className="text-center mb-12">
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-3">Frequently Asked Questions</h2>
          <p className="text-slate-400 text-sm">Everything you need to know about MyAI Vault.</p>
        </div>

        <div className="space-y-4">
          {faqs.map((faq, idx) => (
            <div
              key={idx}
              className="rounded-xl bg-slate-900/60 border border-white/10 overflow-hidden transition-all"
            >
              <button
                onClick={() => setActiveFaq(activeFaq === idx ? null : idx)}
                className="w-full px-6 py-4 text-left font-medium text-white flex items-center justify-between text-base"
              >
                <span>{faq.q}</span>
                <span className="text-sky-400 text-xl">{activeFaq === idx ? '−' : '+'}</span>
              </button>
              {activeFaq === idx && (
                <div className="px-6 pb-5 text-sm text-slate-300 border-t border-white/5 pt-3 leading-relaxed">
                  {faq.a}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Bottom Call To Action Banner */}
      <section className="relative z-10 max-w-5xl mx-auto px-6 py-16">
        <div className="rounded-3xl bg-gradient-to-r from-blue-900/80 via-sky-900/60 to-indigo-900/80 border border-sky-500/30 p-10 sm:p-14 text-center backdrop-blur-xl relative overflow-hidden shadow-2xl">
          <div className="relative z-10 max-w-2xl mx-auto">
            <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
              Ready to Activate Your AI Career Vault?
            </h2>
            <p className="text-slate-300 mb-8 text-base">
              Upload your first certificate or resume and let Gemini AI structure your digital identity in seconds.
            </p>
            <button
              onClick={onGetStarted}
              className="px-8 py-4 rounded-xl bg-gradient-to-r from-sky-400 to-blue-500 hover:from-sky-300 hover:to-blue-400 text-slate-950 font-bold text-base shadow-xl shadow-sky-400/20 transition-all transform hover:scale-105"
            >
              Open MyAI Vault Now
            </button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 border-t border-white/10 bg-slate-950/80 py-10 text-xs text-slate-500 text-center">
        <div className="max-w-6xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center space-x-2">
            <Bot className="w-4 h-4 text-sky-400" />
            <span className="font-semibold text-slate-300">MyAI Vault</span>
            <span>— Your Journey. Understood by AI.</span>
          </div>
          <div>© {new Date().getFullYear()} MyAI Vault Digital Identity Engine. All rights reserved.</div>
        </div>
      </footer>

      {/* Demo Modal */}
      <AnimatePresence>
        {showDemoModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.95, y: 10 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.95, y: 10 }}
              className="bg-[#0B1F3A] border border-sky-500/30 rounded-2xl p-6 sm:p-8 max-w-2xl w-full text-white shadow-2xl relative"
            >
              <button
                onClick={() => setShowDemoModal(false)}
                className="absolute top-4 right-4 text-slate-400 hover:text-white p-2 rounded-lg bg-white/5"
              >
                <X className="w-5 h-5" />
              </button>

              <div className="flex items-center space-x-3 mb-6">
                <div className="p-3 bg-sky-500/20 text-sky-400 rounded-xl">
                  <Play className="w-6 h-6 fill-sky-400" />
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white">MyAI Vault Guided Tour</h3>
                  <p className="text-xs text-slate-400">See how documents transform into an intelligent identity system</p>
                </div>
              </div>

              <div className="space-y-4 mb-8 text-sm">
                <div className="p-4 rounded-xl bg-slate-900/70 border border-white/10 flex items-start space-x-3">
                  <CheckCircle2 className="w-5 h-5 text-sky-400 shrink-0 mt-0.5" />
                  <div>
                    <strong className="text-white block mb-0.5">1. Drag & Drop Upload</strong>
                    <p className="text-slate-300 text-xs">
                      Drop PDFs, certificates, or resumes. OCR extracts text and Gemini extracts key skills.
                    </p>
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-900/70 border border-white/10 flex items-start space-x-3">
                  <CheckCircle2 className="w-5 h-5 text-sky-400 shrink-0 mt-0.5" />
                  <div>
                    <strong className="text-white block mb-0.5">2. Automated Knowledge Graphing</strong>
                    <p className="text-slate-300 text-xs">
                      See certificates connect to capstone projects, internships, and target role goals automatically.
                    </p>
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-900/70 border border-white/10 flex items-start space-x-3">
                  <CheckCircle2 className="w-5 h-5 text-sky-400 shrink-0 mt-0.5" />
                  <div>
                    <strong className="text-white block mb-0.5">3. RAG Conversational Q&A & ATS Score</strong>
                    <p className="text-slate-300 text-xs">
                      Chat with your vault to find Python projects or evaluate your ATS score against top jobs.
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex justify-end space-x-3">
                <button
                  onClick={() => setShowDemoModal(false)}
                  className="px-5 py-2.5 rounded-xl text-slate-300 hover:text-white text-sm"
                >
                  Close
                </button>
                <button
                  onClick={() => {
                    setShowDemoModal(false);
                    onGetStarted();
                  }}
                  className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-sky-400 to-blue-500 text-slate-950 font-bold text-sm shadow-lg shadow-sky-400/20"
                >
                  Enter Sample Vault Now
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
