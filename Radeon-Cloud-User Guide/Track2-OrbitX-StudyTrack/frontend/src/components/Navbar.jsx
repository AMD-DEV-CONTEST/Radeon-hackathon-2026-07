import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { LayoutDashboard, BookOpen, Briefcase, LogOut, User } from 'lucide-react'

export default function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <nav className="navbar">
      <NavLink to="/dashboard" className="nav-brand">
        <span className="nav-title">StudyTrack</span>
        <span className="nav-subtitle">AI-Based Adaptive Learning & Skill Gap Analysis System</span>
      </NavLink>

      <div className="nav-links">
        <NavLink
          to="/dashboard"
          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
        >
          <LayoutDashboard size={16} />
          Dashboard
        </NavLink>
        <NavLink
          to="/academic"
          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
        >
          <BookOpen size={16} />
          Academic
        </NavLink>
        <NavLink
          to="/career"
          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
        >
          <Briefcase size={16} />
          Career
        </NavLink>

        <div className="nav-user-pill">
          <User size={14} />
          <span style={{ fontWeight:600, color:'var(--text-primary)' }}>{user?.username}</span>
        </div>
        <button
          className="nav-link"
          onClick={handleLogout}
          title="Logout"
          style={{ color:'var(--danger)', opacity:0.8 }}
        >
          <LogOut size={16} />
        </button>
      </div>
    </nav>
  )
}
