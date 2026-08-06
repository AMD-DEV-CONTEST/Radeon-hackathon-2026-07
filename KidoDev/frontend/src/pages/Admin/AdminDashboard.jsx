import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase } from '../../utils/supabaseClient';
import { FaLock, FaSignOutAlt, FaTachometerAlt } from 'react-icons/fa';
import AdminOverview from './views/AdminOverview';
import AdminUsers from './views/AdminUsers';
import AdminContent from './views/AdminContent';
import AdminSettings from './views/AdminSettings';
import AdminLessons from './views/AdminLessons';
import AdminProjectManager from './views/AdminProjectManager';
import './AdminDashboard.css';

const NAV_ITEMS = [
    { id: 'overview', label: 'Dashboard' },
    { id: 'lessons', label: 'Lessons' },
    { id: 'projects', label: 'Project Mgr' },
    { id: 'users', label: 'User Base' },
    { id: 'content', label: 'Publish' },
    { id: 'settings', label: 'Access' },
];

const AdminDashboard = () => {
    const [activeView, setActiveView] = useState('overview');
    const [isAuthorized, setIsAuthorized] = useState(null);
    const [loggingOut, setLoggingOut] = useState(false);
    const navigate = useNavigate();

    const handleLogout = async () => {
        setLoggingOut(true);
        localStorage.removeItem('kido_admin_bypass');
        await supabase.auth.signOut();
        navigate('/');
    };

    useEffect(() => {
        const checkAuth = async () => {
            if (localStorage.getItem('kido_admin_bypass') === 'true') {
                setIsAuthorized(true);
                return;
            }
            const { data: { user } } = await supabase.auth.getUser();
            if (user?.email?.toLowerCase() === 'admin@gmail.com') {
                setIsAuthorized(true);
            } else {
                setIsAuthorized(false);
            }
        };
        checkAuth();
    }, []);

    if (isAuthorized === null) return (
        <div className="admin-locked-screen">
            <div className="spinner-border text-primary" />
        </div>
    );

    if (isAuthorized === false) {
        return (
            <div className="admin-locked-screen">
                <div className="admin-lock-card">
                    <div className="lock-icon-wrapper">
                        <FaLock className="lock-icon" />
                    </div>
                    <h2>Access Denied</h2>
                    <p>This administrative zone is restricted to authorized personnel only.</p>
                    <button className="btn btn-primary rounded-pill px-4" onClick={() => window.location.href = '/'}>
                        Return to Safety
                    </button>
                </div>
                <style>{`
                    .admin-locked-screen { height:100vh; display:flex; align-items:center; justify-content:center; background:#F8FAFC; font-family:'Fredoka', sans-serif; }
                    .admin-lock-card { text-align:center; padding:40px; background:#fff; border-radius:24px; box-shadow:0 20px 40px rgba(0,0,0,0.05); max-width:400px; }
                    .lock-icon-wrapper { width:80px; height:80px; background:#FEF2F2; border-radius:50%; display:flex; align-items:center; justify-content:center; margin:0 auto 24px; }
                    .lock-icon { font-size:32px; color:#EF4444; }
                    .admin-lock-card h2 { font-weight:900; color:#1E293B; margin-bottom:12px; }
                    .admin-lock-card p { color:#64748B; font-size:0.95rem; line-height:1.6; margin-bottom:24px; }
                `}</style>
            </div>
        );
    }

    const renderView = () => {
        switch (activeView) {
            case 'overview': return <AdminOverview />;
            case 'lessons': return <AdminLessons />;
            case 'projects': return <AdminProjectManager />;
            case 'users': return <AdminUsers />;
            case 'content': return <AdminContent />;
            case 'settings': return <AdminSettings />;
            default: return <AdminOverview />;
        }
    };

    return (
        <div className="admin-wrapper">
            <nav className="admin-nav">
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginRight: 16 }}>
                    <FaTachometerAlt style={{ color: '#8BC34A', fontSize: 18 }} />
                    <span style={{ fontWeight: 900, fontSize: 15, color: '#1E293B', letterSpacing: '-0.5px' }}>Kido Admin</span>
                </div>
                <div style={{ display: 'flex', gap: 10, flex: 1, flexWrap: 'wrap' }}>
                    {NAV_ITEMS.map(item => (
                        <button
                            key={item.id}
                            className={`admin-nav-btn ${activeView === item.id ? 'active' : ''}`}
                            onClick={() => setActiveView(item.id)}
                            style={{ position: 'relative' }}
                        >
                            {item.label}
                            {item.badge && (
                                <span style={{
                                    position: 'absolute', top: -6, right: -6,
                                    background: item.badge === 'Live' ? '#22c55e' : '#E31937',
                                    color: '#fff', fontSize: 8, fontWeight: 900,
                                    borderRadius: 6, padding: '1px 4px',
                                    letterSpacing: '0.3px',
                                }}>
                                    {item.badge}
                                </span>
                            )}
                        </button>
                    ))}
                </div>
                <button
                    onClick={handleLogout}
                    disabled={loggingOut}
                    style={{
                        display: 'flex', alignItems: 'center', gap: 8,
                        padding: '8px 20px',
                        background: loggingOut ? '#94A3B8' : 'linear-gradient(135deg, #EF4444, #DC2626)',
                        color: '#fff', border: 'none', borderRadius: 12,
                        fontWeight: 800, fontSize: 13,
                        cursor: loggingOut ? 'not-allowed' : 'pointer',
                        boxShadow: '0 4px 12px rgba(239,68,68,0.3)',
                        transition: 'all 0.2s', flexShrink: 0, fontFamily: 'inherit'
                    }}
                    title="Logout from Admin Panel"
                >
                    <FaSignOutAlt size={13} />
                    {loggingOut ? 'Logging out...' : 'Logout'}
                </button>
            </nav>

            <main className="admin-container">
                {renderView()}
            </main>
        </div>
    );
};

export default AdminDashboard;