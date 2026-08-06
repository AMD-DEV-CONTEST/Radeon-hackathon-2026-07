import React from 'react';

const NAV_ITEMS = [
    { id: 'overview', label: 'Command Overview', group: 'MAIN' },
    { id: 'users', label: 'User Management', group: 'MAIN' },
    { id: 'content', label: 'Add Content', group: 'CONTENT' },
    { id: 'content-manage', label: 'Manage Content', group: 'CONTENT' },
    { id: 'settings', label: 'Register Partner', group: 'ADMIN' },
];

const AdminSidebar = ({ activeView, setActiveView }) => {
    const groups = [...new Set(NAV_ITEMS.map(n => n.group))];

    return (
        <aside className="ad-sidebar">
            <div className="ad-sidebar-brand">
                <div className="ad-brand-logo">K</div>
                <div className="ad-brand-text">
                    <span className="ad-brand-name">Kido Dev</span>
                    <span className="ad-brand-role">Command Center</span>
                </div>
            </div>

            <nav className="ad-nav">
                {groups.map(group => (
                    <div key={group} className="ad-nav-group">
                        <span className="ad-nav-group-label">{group}</span>
                        {NAV_ITEMS.filter(n => n.group === group).map(item => (
                            <button
                                key={item.id}
                                className={`ad-nav-item ${activeView === item.id ? 'active' : ''}`}
                                onClick={() => setActiveView(item.id)}
                            >
                                <span className="ad-nav-dot"></span>
                                {item.label}
                                {activeView === item.id && <span className="ad-nav-active-bar"></span>}
                            </button>
                        ))}
                    </div>
                ))}
            </nav>

            <div className="ad-sidebar-footer">
                <div className="ad-sidebar-avatar">A</div>
                <div className="ad-sidebar-user">
                    <span className="ad-sidebar-user-email">Super Admin</span>
                    <span className="ad-sidebar-user-role">ADMINISTRATOR</span>
                </div>
            </div>
        </aside>
    );
};

export default AdminSidebar;
