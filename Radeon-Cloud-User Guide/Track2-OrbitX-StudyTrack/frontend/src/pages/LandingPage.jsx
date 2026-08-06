import { useNavigate } from 'react-router-dom'
import { Brain, Target, TrendingUp, Briefcase, ArrowRight } from 'lucide-react'

const LogoIcon = () => (
  <svg width="28" height="32" viewBox="0 0 28 32" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M22 4H6C4.895 4 4 4.895 4 6v2.5c3.314 0 6 2.239 6 5s-2.686 5-6 5H6c-1.105 0-2 .895-2 2v2.5c0 1.105.895 2 2 2h12c3.314 0 6-2.239 6-5v-2.5c-3.314 0-6-2.239-6-5s2.686-5 6-5h-2c-1.105 0-2-.895-2-2V6c0-1.105.895-2 2-2h2c1.105 0 2 .895 2 2v8h2c1.105 0 2-.895 2-2V6c0-1.105-.895-2-2-2z" fill="url(#logoGrad)"/>
    <defs>
      <linearGradient id="logoGrad" x1="2" y1="16" x2="26" y2="16">
        <stop offset="0%" stopColor="#F472B6" />
        <stop offset="100%" stopColor="#A855F7" />
      </linearGradient>
    </defs>
  </svg>
)

export default function LandingPage() {
  const navigate = useNavigate()

  return (
    <div className="landing-page">
      <div className="landing-bg-orb landing-bg-orb-1" />
      <div className="landing-bg-orb landing-bg-orb-2" />
      <div className="landing-bg-orb landing-bg-orb-3" />

      <nav className="landing-nav">
        <div className="landing-nav-inner">
          <div className="landing-logo">
            <LogoIcon />
            <span className="landing-logo-text">StudyTrack</span>
          </div>
          <div className="landing-nav-actions">
            <button onClick={() => navigate('/login')} className="landing-nav-link">Login</button>
            <button onClick={() => navigate('/register')} className="landing-btn-primary">Register</button>
          </div>
        </div>
      </nav>

      <main className="landing-main">
        <div className="landing-hero">
          <div className="landing-hero-left animate-fadeInUp">
            <div className="landing-badge">
              + AI-POWERED LEARNING PLATFORM
            </div>
            <h1 className="landing-heading">
              Learn <span className="landing-heading-accent">Smarter.</span><br />
              Improve <span className="landing-heading-accent">Faster.</span><br />
              Build Your <span className="landing-heading-accent">Career.</span>
            </h1>
            <p className="landing-description">
              StudyTrack uses AI-powered learning analysis and skill gap detection to help students
              understand their progress, improve weak areas, and prepare for their career goals.
            </p>

            <div className="landing-features">
              <div className="landing-feature">
                <div className="landing-feature-icon">
                  <Brain size={16} />
                </div>
                <span>AI Learning Analysis</span>
              </div>
              <div className="landing-feature">
                <div className="landing-feature-icon">
                  <Target size={16} />
                </div>
                <span>Skill Gap Detection</span>
              </div>
              <div className="landing-feature">
                <div className="landing-feature-icon">
                  <TrendingUp size={16} />
                </div>
                <span>Personalized Recommendations</span>
              </div>
              <div className="landing-feature">
                <div className="landing-feature-icon">
                  <Briefcase size={16} />
                </div>
                <span>Career Readiness Tracking</span>
              </div>
            </div>

            <div className="landing-cta">
              <button onClick={() => navigate('/register')} className="landing-btn-hero">
                Start Learning <ArrowRight size={18} />
              </button>
            </div>
          </div>

          <div className="landing-hero-right animate-fadeIn">
            <div className="ai-visual">
              <div className="ai-visual-grid">
                <div className="ai-card ai-card-1">
                  <div className="ai-card-icon"><Brain size={22} /></div>
                  <div className="ai-card-title">AI Quiz Generator</div>
                  <div className="ai-card-desc">Generate intelligent assessments from study materials</div>
                </div>
                <div className="ai-card ai-card-2">
                  <div className="ai-card-icon"><Target size={22} /></div>
                  <div className="ai-card-title">Skill Gap Detection</div>
                  <div className="ai-card-desc">Identify missing skills and improve weak areas</div>
                </div>
                <div className="ai-card ai-card-3">
                  <div className="ai-card-icon"><TrendingUp size={22} /></div>
                  <div className="ai-card-title">Personalized Learning</div>
                  <div className="ai-card-desc">Adaptive recommendations for better learning</div>
                </div>
                <div className="ai-card ai-card-4">
                  <div className="ai-card-icon"><Briefcase size={22} /></div>
                  <div className="ai-card-title">Career Preparation</div>
                  <div className="ai-card-desc">Build skills for future career goals</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <section className="landing-features-section animate-fadeInUp">
          <div className="landing-features-grid">
            <div className="landing-feature-card">
              <div className="landing-feature-card-icon">
                <Brain size={24} />
              </div>
              <h3 className="landing-feature-card-title">AI-Based Academic Analysis</h3>
              <p className="landing-feature-card-desc">
                Get intelligent insights into your academic performance with AI-driven topic analysis
                and personalized learning path recommendations.
              </p>
            </div>
            <div className="landing-feature-card">
              <div className="landing-feature-card-icon">
                <TrendingUp size={24} />
              </div>
              <h3 className="landing-feature-card-title">Adaptive Learning Insights</h3>
              <p className="landing-feature-card-desc">
                Receive real-time adaptive recommendations that evolve with your progress,
                helping you focus on the areas that matter most.
              </p>
            </div>
            <div className="landing-feature-card">
              <div className="landing-feature-card-icon">
                <Briefcase size={24} />
              </div>
              <h3 className="landing-feature-card-title">Career Skill Assessment</h3>
              <p className="landing-feature-card-desc">
                Evaluate your career readiness with comprehensive skill gap analysis and
                targeted preparation for your professional goals.
              </p>
            </div>
          </div>
        </section>

        <footer className="landing-footer">
          <p>© 2026 StudyTrack. Built with AI for smarter learning.</p>
        </footer>
      </main>
    </div>
  )
}
