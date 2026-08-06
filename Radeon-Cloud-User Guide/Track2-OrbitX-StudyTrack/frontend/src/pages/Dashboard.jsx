import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api } from '../api'
import { BookOpen, Briefcase, Trophy, Target, FileText, Clock } from 'lucide-react'

const SCORE_COLOR = (s) => s >= 75 ? '#16A34A' : s >= 50 ? '#D97706' : '#DC2626'

function WelcomeSection({ user, onNavigate }) {
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'

  return (
    <div className="welcome-section">
      <div>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, marginBottom: '0.25rem' }}>
          {greeting}, <span style={{ color: 'var(--primary)' }}>{user?.username}</span>
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
          Track your academic progress and career readiness from one place.
        </p>
      </div>
      <div className="welcome-actions">
        <button onClick={() => onNavigate('/academic')} className="btn btn-primary btn-lg" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <BookOpen size={18} /> Start Academic Quiz
        </button>
        <button onClick={() => onNavigate('/career')} className="btn btn-secondary btn-lg" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Target size={18} /> Start Career Assessment
        </button>
      </div>
    </div>
  )
}

function SummaryCard({ icon: Icon, label, value, color, index }) {
  const iconBg = {
    'var(--primary)': 'var(--accent-blue)',
    'var(--warning)': 'var(--warning-soft)',
    'var(--success)': 'var(--success-soft)'
  }

  const bg = iconBg[color] || 'var(--accent-blue)'

  return (
    <div className="summary-card animate-fadeInUp" style={{ '--delay': `${index * 0.08}s` }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
        <div style={{ width: 42, height: 42, borderRadius: 16, background: bg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Icon size={20} style={{ color }} />
        </div>
      </div>
      <div style={{ fontSize: '2rem', fontWeight: 700, color, lineHeight: 1, marginBottom: '0.25rem' }}>
        {value}
      </div>
      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
        {label}
      </div>
    </div>
  )
}

function RecentActivityItem({ icon: Icon, title, score, date, onViewReport }) {
  return (
    <div className="activity-item">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1 }}>
        <div style={{ width: 36, height: 36, borderRadius: 12, background: 'var(--accent-lavender)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
          <Icon size={16} style={{ color: 'var(--primary)' }} />
        </div>
        <div style={{ flex: 1 }}>
          <p style={{ fontWeight: 600, fontSize: '0.925rem', margin: 0 }}>{title}</p>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', margin: 0 }}>{date}</p>
        </div>
        <div style={{ fontSize: '1.1rem', fontWeight: 700, color: SCORE_COLOR(score), minWidth: 50, textAlign: 'right' }}>
          {score}%
        </div>
      </div>
      <button onClick={onViewReport} className="btn btn-ghost btn-sm" style={{ marginLeft: '0.75rem' }}>
        <FileText size={14} /> View Report
      </button>
    </div>
  )
}

function RecentActivity({ academicSessions, careerSessions, onViewReport }) {
  if (!academicSessions?.length && !careerSessions?.length) {
    return (
      <div className="card activity-empty">
        <div style={{ textAlign: 'center', padding: '2rem 1rem' }}>
          <div style={{ width: 64, height: 64, borderRadius: 16, background: 'var(--accent-lavender)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 1rem' }}>
            <Clock size={28} style={{ color: 'var(--primary)', opacity: 0.7 }} />
          </div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', marginBottom: '1.5rem' }}>
            No activity yet. Start your first quiz or assessment to see your progress here.
          </p>
          <div style={{ display: 'flex', gap: '1rem', justifyContent: 'center' }}>
            <button onClick={() => onViewReport('academic')} className="btn btn-primary">
              <BookOpen size={16} /> Start Academic Quiz
            </button>
            <button onClick={() => onViewReport('career')} className="btn btn-secondary">
              <Target size={16} /> Start Career Assessment
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <h3 style={{ marginBottom: '1rem', fontSize: '1rem', fontWeight: 700 }}>Recent Activity</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {academicSessions?.slice(0, 2).map((session, i) => (
          <RecentActivityItem
            key={`academic-${i}`}
            icon={BookOpen}
            title={`Academic Quiz: ${session.subject} - ${session.topic}`}
            score={session.score}
            date={new Date(session.created_at).toLocaleDateString()}
            onViewReport={() => onViewReport('academic')}
          />
        ))}
        {careerSessions?.slice(0, 2).map((session, i) => (
          <RecentActivityItem
            key={`career-${i}`}
            icon={Briefcase}
            title={`Career Assessment: ${session.career_goal}`}
            score={session.overall_readiness}
            date={new Date(session.created_at).toLocaleDateString()}
            onViewReport={() => onViewReport('career')}
          />
        ))}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [academicData, setAcademicData] = useState(null)
  const [careerData, setCareerData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.get('/api/academic/report').catch(() => ({ data: null })),
      api.get('/api/career/report').catch(() => ({ data: null }))
    ]).then(([ac, ca]) => {
      setAcademicData(ac.data)
      setCareerData(ca.data)
      setLoading(false)
    })
  }, [])

  const handleNavigate = (path) => navigate(path)
  const handleViewReport = (type) => navigate(type === 'academic' ? '/academic' : '/career')

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', flexDirection: 'column', gap: '1rem' }}>
      <div className="spinner-lg spinner" />
      <p style={{ color: 'var(--text-muted)' }}>Loading your dashboard...</p>
    </div>
  )

  const academicSessions = academicData?.recent_sessions || []
  const careerSessions = careerData?.recent_sessions || []
  const hasAcademic = academicData?.total_sessions > 0
  const hasCareer = careerData?.total_sessions > 0

  const avgAcademicScore = hasAcademic
    ? Math.round(academicSessions.reduce((a, s) => a + s.score, 0) / academicSessions.length)
    : '--'

  const careerReadiness = hasCareer
    ? `${careerData.report[0].overall_readiness.toFixed(0)}%`
    : '--'

  return (
    <div className="page-container animate-fadeIn" style={{ maxWidth: '1100px' }}>
      <WelcomeSection user={user} onNavigate={handleNavigate} />

      <div className="summary-grid">
        <SummaryCard icon={BookOpen} label="Academic Sessions" value={academicData?.total_sessions || 0} color="var(--primary)" index={0} />
        <SummaryCard icon={Briefcase} label="Career Assessments" value={careerData?.total_sessions || 0} color="var(--primary)" index={1} />
        <SummaryCard icon={Trophy} label="Avg Academic Score" value={avgAcademicScore} color="var(--warning)" index={2} />
        <SummaryCard icon={Target} label="Career Readiness" value={careerReadiness} color="var(--success)" index={3} />
      </div>

      <RecentActivity
        academicSessions={academicSessions}
        careerSessions={careerSessions}
        onViewReport={handleViewReport}
      />
    </div>
  )
}