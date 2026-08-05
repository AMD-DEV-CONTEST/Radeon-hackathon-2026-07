import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, NavLink, useNavigate, useLocation, Navigate } from 'react-router-dom'
import { Shield, Terminal, Activity, Server, Sun, Moon, HelpCircle, X, CheckCircle2, ArrowRight, ArrowLeft, ChevronLeft, ChevronRight, Zap, Sparkles, FileCode } from 'lucide-react'
import LandingPage from './pages/LandingPage'
import ReviewPage from './pages/ReviewPage'
import BenchmarkPage from './pages/BenchmarkPage'
import './index.css'

const TOUR_STEPS = [
  {
    title: '1. Select Audit Target',
    subtitle: 'Target Preset Repository or Custom GitHub PR',
    color: '#00f0ff',
    desc: 'Select from 20+ real open-source repository presets (Express, Flask, Kubernetes, Redis) or enter any custom public GitHub owner/repo and PR number.'
  },
  {
    title: '2. 5-Agent Tribunal Pipeline',
    subtitle: 'Parallel State Orchestration with LangGraph',
    color: '#a855f7',
    desc: 'Watch Triage Engine, Security RAG, Style Inspector, Verifier Gate, and Fix Generator nodes run concurrently with real-time state reducers.'
  },
  {
    title: '3. Live Telemetry & Verified Findings',
    subtitle: 'OWASP Top 10 & CWE Vector Embedding Matching',
    color: '#ff2d55',
    desc: 'Inspect real-time log streams, CWE rule classifications, confidence scores, and syntax-highlighted git diff patch remediations.'
  },
  {
    title: '4. Metrics Board & 1-Click Exports',
    subtitle: 'OASIS SARIF 2.1.0, JSON, & Live GitHub PR Fix',
    color: '#30d158',
    desc: 'Export security reports in standard SARIF 2.1.0 or JSON, review historical session metrics, and click Approve Patches to submit live Pull Requests.'
  }
]

function WelcomeGuideModal({ isOpen, onClose }) {
  const [step, setStep] = useState(0)

  if (!isOpen) return null

  const currentStep = TOUR_STEPS[step]

  const handleNext = () => {
    if (step < TOUR_STEPS.length - 1) {
      setStep(step + 1)
    } else {
      onClose()
    }
  }

  const handlePrev = () => {
    if (step > 0) {
      setStep(step - 1)
    }
  }

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(5, 7, 10, 0.85)',
      backdropFilter: 'blur(12px)',
      zIndex: 9999,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '1.5rem'
    }}>
      <div style={{
        background: 'var(--bg-surface)',
        border: `1px solid ${currentStep.color}`,
        borderRadius: '24px',
        maxWidth: '640px',
        width: '100%',
        padding: '2.25rem',
        boxShadow: `0 25px 60px -12px ${currentStep.color}33`,
        position: 'relative',
        transition: 'all 0.3s ease'
      }}>
        <button 
          onClick={onClose}
          style={{
            position: 'absolute',
            top: '1.25rem',
            right: '1.25rem',
            background: 'rgba(255, 255, 255, 0.06)',
            border: '1px solid var(--glass-border)',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            padding: '6px',
            borderRadius: '8px'
          }}
        >
          <X size={18} />
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '1.5rem' }}>
          <div style={{
            width: '44px',
            height: '44px',
            borderRadius: '12px',
            background: `${currentStep.color}22`,
            border: `1px solid ${currentStep.color}66`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <Shield size={22} color={currentStep.color} />
          </div>
          <div>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: currentStep.color }}>
              THEMIS Interactive Tour • Step {step + 1} of {TOUR_STEPS.length}
            </div>
            <h3 style={{ fontSize: '1.35rem', fontWeight: 800, color: 'var(--text-primary)', marginTop: '2px' }}>
              {currentStep.title}
            </h3>
          </div>
        </div>

        {/* Step Indicator Bar */}
        <div style={{ display: 'flex', gap: '8px', marginBottom: '1.5rem' }}>
          {TOUR_STEPS.map((s, idx) => (
            <div 
              key={idx}
              onClick={() => setStep(idx)}
              style={{
                flex: 1,
                height: '4px',
                borderRadius: '2px',
                background: idx === step ? currentStep.color : idx < step ? `${s.color}aa` : 'var(--glass-border)',
                cursor: 'pointer',
                transition: 'all 0.3s ease'
              }}
            />
          ))}
        </div>

        <div style={{
          padding: '1.25rem',
          borderRadius: '14px',
          background: 'var(--bg-deep)',
          border: '1px solid var(--glass-border)',
          marginBottom: '1.75rem'
        }}>
          <div style={{ fontWeight: 700, color: 'var(--text-primary)', marginBottom: '6px', fontSize: '0.95rem' }}>
            {currentStep.subtitle}
          </div>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
            {currentStep.desc}
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
          <button
            onClick={handlePrev}
            disabled={step === 0}
            style={{
              padding: '0.75rem 1.25rem',
              borderRadius: '10px',
              background: 'var(--bg-deep)',
              border: '1px solid var(--glass-border)',
              color: 'var(--text-primary)',
              fontWeight: 600,
              cursor: step === 0 ? 'not-allowed' : 'pointer',
              opacity: step === 0 ? 0.4 : 1,
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <ArrowLeft size={16} />
            <span>Previous</span>
          </button>

          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              onClick={onClose}
              style={{
                padding: '0.75rem 1.25rem',
                borderRadius: '10px',
                background: 'transparent',
                border: 'none',
                color: 'var(--text-muted)',
                fontWeight: 600,
                cursor: 'pointer'
              }}
            >
              Skip Tour
            </button>

            <button
              onClick={handleNext}
              style={{
                padding: '0.75rem 1.5rem',
                borderRadius: '10px',
                background: `linear-gradient(135deg, ${currentStep.color}, ${currentStep.color}dd)`,
                color: step === 0 || step === 3 ? '#000000' : '#ffffff',
                fontWeight: 700,
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                boxShadow: `0 0 20px ${currentStep.color}44`
              }}
            >
              <span>{step === TOUR_STEPS.length - 1 ? 'Start Exploring' : 'Next Step'}</span>
              <ArrowRight size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}



function Navbar({ theme, toggleTheme, onOpenGuide }) {
  const [isLive, setIsLive] = useState(true)

  useEffect(() => {
    // Check backend API connection immediately and poll every 10s
    const checkHealth = () => {
      fetch('/api/health')
        .then(res => setIsLive(res.ok))
        .catch(() => setIsLive(false))
    }
    
    checkHealth()
    const interval = setInterval(checkHealth, 10000)
    return () => clearInterval(interval)
  }, [])

  return (
    <nav className="navbar">
      <div className="navbar-inner">
        <NavLink to="/" className="navbar-brand">
          <div className="logo-icon">
            <Shield size={18} color="#ffffff" />
          </div>
          <span>THEMIS</span>
        </NavLink>

        <div className="navbar-links">
          <NavLink to="/tribunal" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <Terminal size={14} />
            <span>Tribunal</span>
          </NavLink>



          <NavLink to="/benchmark" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <Activity size={14} />
            <span>Benchmark</span>
          </NavLink>

          <button 
            onClick={onOpenGuide} 
            className="nav-link" 
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
            title="User Guide & System Walkthrough"
          >
            <HelpCircle size={14} />
            <span>Guide</span>
          </button>

          <button 
            onClick={toggleTheme} 
            className="nav-link" 
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px 8px', borderRadius: '6px', color: 'var(--text-primary)' }}
            title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
          >
            {theme === 'dark' ? <Sun size={16} color="#ffd60a" /> : <Moon size={16} color="#a855f7" />}
          </button>

          <div className={`status-online ${isLive ? 'live' : 'offline'}`}>
            <span className={`status-beacon ${isLive ? 'done' : 'critical'}`} style={{ width: 6, height: 6 }} />
            <span>{isLive ? 'LIVE' : 'OFFLINE'}</span>
          </div>

          <span className="nav-badge" style={{ padding: '3px 8px', fontSize: '0.65rem' }}>
            <Server size={10} style={{ display: 'inline', marginRight: 3 }} />
            AMD ROCm
          </span>
        </div>
      </div>
    </nav>
  )
}

export default function App() {
  const [theme, setTheme] = useState('dark')
  const [isGuideOpen, setIsGuideOpen] = useState(false)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  useEffect(() => {
    const hasSeenTour = localStorage.getItem('themis_tour_completed')
    if (!hasSeenTour) {
      setIsGuideOpen(true)
      localStorage.setItem('themis_tour_completed', 'true')
    }
  }, [])

  const toggleTheme = () => {
    setTheme(prev => (prev === 'dark' ? 'light' : 'dark'))
  }

  return (
    <BrowserRouter>
      <Navbar theme={theme} toggleTheme={toggleTheme} onOpenGuide={() => setIsGuideOpen(true)} />
      <WelcomeGuideModal isOpen={isGuideOpen} onClose={() => setIsGuideOpen(false)} />
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/tribunal" element={<ReviewPage />} />
        <Route path="/review" element={<ReviewPage />} />
        <Route path="/benchmark" element={<BenchmarkPage />} />
      </Routes>
    </BrowserRouter>
  )
}
