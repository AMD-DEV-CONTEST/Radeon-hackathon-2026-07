import { useNavigate } from 'react-router-dom'
import {
  Shield,
  ShieldCheck,
  Cpu,
  Database,
  Lock,
  Activity,
  BarChart3,
  Layers,
  Sparkles
} from 'lucide-react'

const FEATURES = [
  {
    icon: Layers,
    accent: '#a855f7',
    title: '5-Agent Parallel Tribunal',
    desc: 'Specialized node execution for triage, static security analysis, style validation, confidence verification, and patch generation.'
  },
  {
    icon: Database,
    accent: '#00f0ff',
    title: 'Grounded Vector RAG',
    desc: 'Dense embeddings and Qdrant vector search cross-reference findings directly against verified OWASP and CWE databases.'
  },
  {
    icon: Cpu,
    accent: '#ff2d55',
    title: 'AMD Hardware Acceleration',
    desc: 'Qwen2.5-Coder-32B INT4 AWQ inference hosted on 48GB VRAM with ROCm 7.2.1 optimization.'
  },
  {
    icon: Lock,
    accent: '#ffd60a',
    title: 'Human Approval Gate',
    desc: 'Automated patch generation requires human verification before opening pull requests.'
  },
  {
    icon: ShieldCheck,
    accent: '#30d158',
    title: 'Isolated Execution',
    desc: 'Static analysis tools run in ephemeral containers with restricted system permissions and zero network egress.'
  },
  {
    icon: Activity,
    accent: '#ff6b35',
    title: 'Hardware Telemetry',
    desc: 'Real-time throughput metrics, latency timing, and time-to-first-token benchmarks.'
  }
]

export default function LandingPage() {
  const navigate = useNavigate()

  return (
    <main className="page landing-page">
      {/* Hero Section */}
      <header className="hero-section">
        <div className="hero-badge">
          <Sparkles size={14} />
          <span>AMD AI DevMaster Hackathon 2026 : Team Alchemy</span>
        </div>

        <h1 className="hero-title">
          Autonomous Code Review & Security Analysis Platform
        </h1>

        <p className="hero-subtitle page-subtitle">
          THEMIS deploys five specialized AI agents to inspect pull requests, identify vulnerabilities, verify CWE compliance, and generate validated fixes on AMD Radeon hardware.
        </p>

        <div className="hero-actions">
          <button className="btn btn-primary btn-lg" onClick={() => navigate('/tribunal')}>
            <Shield size={18} />
            <span>Launch Tribunal Console</span>
          </button>
          <button className="btn btn-secondary btn-lg" onClick={() => navigate('/benchmark')}>
            <BarChart3 size={18} />
            <span>View Telemetry Benchmarks</span>
          </button>
        </div>
      </header>

      {/* Metrics Section */}
      <section className="metrics-section">
        <div className="metric-grid">
          <div className="metric-card">
            <div className="metric-value">32B</div>
            <div className="metric-label">Model Parameters</div>
          </div>
          <div className="metric-card">
            <div className="metric-value">AWQ</div>
            <div className="metric-label">INT4 Quantization</div>
          </div>
          <div className="metric-card">
            <div className="metric-value">5</div>
            <div className="metric-label">Tribunal Agents</div>
          </div>
          <div className="metric-card">
            <div className="metric-value">48GB</div>
            <div className="metric-label">AMD GPU VRAM</div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="features-section">
        <h2 className="section-label">System Capabilities</h2>
        <div className="feature-grid">
          {FEATURES.map(f => {
            const IconComponent = f.icon
            return (
              <div key={f.title} className="card card-interactive feature-card">
                <div className="feature-icon" style={{ color: f.accent }}>
                  <IconComponent size={28} />
                </div>
                <h3 className="feature-title">{f.title}</h3>
                <p className="feature-desc">{f.desc}</p>
              </div>
            )
          })}
        </div>
      </section>

      {/* Pipeline Architecture Section */}
      <section className="architecture-section">
        <h2 className="section-label">Agent Pipeline Architecture</h2>
        <div className="pipeline-container">
          {['Triage Engine', '→', 'Security RAG', 'Style Engine', '→', 'Verifier Gate', '→', 'Fix Generator', '→', 'Human Approval'].map((step, i) => (
            step === '→' ? (
              <span key={i} className="pipeline-arrow">→</span>
            ) : (
              <span key={i} className="pipeline-node">
                {step}
              </span>
            )
          ))}
        </div>
      </section>
    </main>
  )
}
