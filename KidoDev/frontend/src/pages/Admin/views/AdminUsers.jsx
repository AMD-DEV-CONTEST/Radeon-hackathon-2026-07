import React, { useState, useEffect } from 'react';
import { supabase } from '../../../utils/supabaseClient';
import { FaSpinner } from 'react-icons/fa';

const AdminUsers = () => {
    const [tab, setTab] = useState('parents');
    const [loading, setLoading] = useState(true);
    const [users, setUsers] = useState([]);
    const [search, setSearch] = useState('');
    const [approvingIds, setApprovingIds] = useState({});

    useEffect(() => { fetchUsers(); }, [tab]);

    const fetchUsers = async () => {
        setLoading(true);
        try {
            const timeout = (ms) => new Promise((_, rej) => setTimeout(() => rej(new Error('T')), ms));
            const fetchSafe = async (q) => {
                try { return await Promise.race([q, timeout(5000)]); } catch(e) { return { data: [], count: 0 }; }
            };

            const pRes = await fetchSafe(supabase.from('parent_profiles').select('id, email'));
            const cRes = await fetchSafe(supabase.from('children').select('id', { count: 'exact', head: true }));
            const sRes = await fetchSafe(supabase.from('schools').select('id', { count: 'exact', head: true }));
            const chRes = await fetchSafe(supabase.from('children').select('parent_email'));

            const uniqueEmails = new Set([
                ...(pRes.data || []).map(p => p.email).filter(Boolean),
                ...(chRes.data || []).map(c => c.parent_email).filter(Boolean)
            ]);

            setSummaryCounts({
                parents: uniqueEmails.size,
                children: cRes.count || 0,
                schools: sRes.count || 0
            });

            let query = tab === 'parents' ? supabase.from('parent_profiles').select('*') : tab === 'children' ? supabase.from('children').select('*') : supabase.from('schools').select('*');
            const { data } = await fetchSafe(query.order('created_at', { ascending: false }));
            if (data) setUsers(data);
        } catch (e) { console.error(e); }
        setLoading(false);
    };

    const [summaryCounts, setSummaryCounts] = useState({ parents: 0, children: 0, schools: 0 });

    const handleUpdateSchoolStatus = async (schoolId, newStatus) => {
        setApprovingIds(prev => ({ ...prev, [schoolId]: true }));
        try {
            const { error } = await supabase.from('schools')
                .update({
                    payment_status: newStatus,
                    status_changed_at: new Date().toISOString()
                })
                .eq('id', schoolId);
            if (error) throw error;
            await fetchUsers();
        } catch (err) {
            alert(err.message);
        } finally {
            setApprovingIds(prev => ({ ...prev, [schoolId]: false }));
        }
    };

    const handleUpdateChildStatus = async (childId, newStatus) => {
        setApprovingIds(prev => ({ ...prev, [childId]: true }));
        try {
            const { error } = await supabase.from('children')
                .update({
                    payment_status: newStatus,
                    status_changed_at: new Date().toISOString()
                })
                .eq('id', childId);
            if (error) throw error;
            await fetchUsers();
        } catch (err) {
            alert(err.message);
        } finally {
            setApprovingIds(prev => ({ ...prev, [childId]: false }));
        }
    };

    const handleDelete = async (id) => {
        if (!window.confirm('Permanently delete this record?')) return;
        try {
            let table = tab === 'parents' ? 'parent_profiles' : tab === 'children' ? 'children' : 'schools';
            const { error } = await supabase.from(table).delete().eq('id', id);
            if (error) throw error;
            setUsers(users.filter(u => u.id !== id));
        } catch (e) {
            alert("Delete failed: " + e.message);
        }
    };

    const filteredUsers = users.filter(u => {
        const str = JSON.stringify(u).toLowerCase();
        return str.includes(search.toLowerCase());
    });

    const formatDate = (isoStr) => {
        if (!isoStr) return '-';
        return new Date(isoStr).toLocaleString();
    };

    return (
        <div>
            <div className="admin-page-header admin-flex-between flex-wrap gap-3">
                <div>
                    <h1 className="admin-page-title">User Base</h1>
                    <p className="admin-page-desc">
                        Managing <strong>{summaryCounts.parents}</strong> Parents, <strong>{summaryCounts.schools}</strong> Schools, and <strong>{summaryCounts.children}</strong> Students
                    </p>
                </div>
                <div className="d-flex gap-3 align-items-center">
                    <div className="admin-summary-pill">
                        <span className="label">Total Users:</span>
                        <span className="value">{summaryCounts.parents + summaryCounts.schools + summaryCounts.children}</span>
                    </div>
                    <input 
                        type="text" 
                        className="admin-input" 
                        placeholder="Search records..." 
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        style={{ width: '300px' }}
                    />
                </div>
            </div>

            <div className="admin-tabs">
                <button className={`admin-tab ${tab === 'parents' ? 'active' : ''}`} onClick={() => setTab('parents')}>
                    Parents ({summaryCounts.parents})
                </button>
                <button className={`admin-tab ${tab === 'children' ? 'active' : ''}`} onClick={() => setTab('children')}>
                    Children ({summaryCounts.children})
                </button>
                <button className={`admin-tab ${tab === 'schools' ? 'active' : ''}`} onClick={() => setTab('schools')}>
                    Schools ({summaryCounts.schools})
                </button>
            </div>

            <div className="admin-card" style={{ padding: 0 }}>
                <div className="admin-table-container">
                    <table className="admin-table">
                            <thead>
                                {tab === 'parents' ? (
                                    <tr><th>Parent Name</th><th>Email Address</th><th>Platform Role</th><th>Payment Status</th><th style={{textAlign:'right'}}>Actions</th></tr>
                                ) : tab === 'children' ? (
                                    <tr><th>Student Name</th><th>Parent Name</th><th>Age</th><th>Gender</th><th>Class</th><th>Secret Key</th><th>Status / Updated At</th><th>Screenshot</th><th style={{textAlign:'right'}}>Actions</th></tr>
                                ) : (
                                    <tr><th>School Name</th><th>Admin Email</th><th>Platform Role</th><th>Payment Status / Updated At</th><th>Screenshot</th><th style={{textAlign:'right'}}>Actions</th></tr>
                                )}
                            </thead>
                            <tbody>
                                {loading && filteredUsers.length === 0 && (
                                    <tr><td colSpan="9" style={{ textAlign: 'center', padding: '40px', color: '#64748B' }}>Fetching records...</td></tr>
                                )}
                                {!loading && filteredUsers.length === 0 && (
                                    <tr><td colSpan="9" style={{ textAlign: 'center', padding: '40px', color: '#64748B' }}>No records found.</td></tr>
                                )}
                                {tab === 'parents' && filteredUsers.map(u => (
                                    <tr key={u.id}>
                                        <td className="admin-text-bold">{u.full_name || 'N/A'}</td>
                                        <td className="admin-text-muted">{u.email}</td>
                                        <td><span className="admin-badge primary">{u.role || 'Parent'}</span></td>
                                        <td>
                                            <span className={`admin-badge ${u.payment_status === 'paid' ? 'success' : 'warning'}`}>
                                                {u.payment_status === 'paid' ? 'Paid (Rs 100)' : 'Pending Checkout'}
                                            </span>
                                        </td>
                                        <td>
                                            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                                                <button className="admin-btn admin-btn-sm admin-btn-danger" onClick={() => handleDelete(u.id)}>Delete</button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                                {tab === 'children' && filteredUsers.map(u => (
                                    <tr key={u.id} style={u.payment_status !== 'paid' && u.screenshot_url ? { backgroundColor: '#FEF2F2' } : {}}>
                                        <td className="admin-text-bold">{u.name}</td>
                                        <td className="admin-text-muted small">{u.parent_name || 'N/A'}</td>
                                        <td>{u.age || '-'}</td>
                                        <td><span className="admin-badge primary">{u.gender || 'Boy'}</span></td>
                                        <td><span className="admin-badge primary">{u.current_level || 'Class 1'}</span></td>
                                        <td style={{ fontFamily: 'monospace', color: '#0EA5E9' }}>{u.secret_key}</td>
                                        <td>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                                <span className={`admin-badge ${u.payment_status === 'paid' ? 'success' : 'warning'}`} style={{ width: 'fit-content' }}>
                                                    {u.payment_status === 'paid' ? 'Verified Access' : 'Awaiting Payment'}
                                                </span>
                                                <span className="small text-muted" style={{ fontSize: '0.75rem' }}>
                                                    {u.status_changed_at ? `Changed: ${formatDate(u.status_changed_at)}` : `Created: ${formatDate(u.created_at)}`}
                                                </span>
                                                {u.payment_status === 'paid' && (
                                                    <span className="small text-danger fw-bold" style={{ fontSize: '0.75rem' }}>
                                                        Expiry: {formatDate(new Date(new Date(u.status_changed_at || u.created_at).getTime() + 30 * 24 * 60 * 60 * 1000).toISOString())}
                                                    </span>
                                                )}
                                            </div>
                                        </td>
                                        <td>
                                            {u.screenshot_url ? (
                                                <a href={u.screenshot_url} target="_blank" rel="noreferrer" className="admin-btn admin-btn-sm admin-btn-primary" style={{ textDecoration: 'none', display: 'inline-block' }}>
                                                    View SS
                                                </a>
                                            ) : (
                                                <span className="text-muted small">None</span>
                                            )}
                                        </td>
                                        <td>
                                            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                                                {u.payment_status !== 'paid' ? (
                                                    <button className="admin-btn admin-btn-sm admin-btn-success" onClick={() => handleUpdateChildStatus(u.id, 'paid')} disabled={approvingIds[u.id]}>
                                                        {approvingIds[u.id] ? <FaSpinner className="fa-spin" /> : 'Approve'}
                                                    </button>
                                                ) : (
                                                    <button className="admin-btn admin-btn-sm admin-btn-warning" onClick={() => handleUpdateChildStatus(u.id, 'pending')} disabled={approvingIds[u.id]}>
                                                        {approvingIds[u.id] ? <FaSpinner className="fa-spin" /> : 'Reject'}
                                                    </button>
                                                )}
                                                <button className="admin-btn admin-btn-sm admin-btn-danger" onClick={() => handleDelete(u.id)} disabled={approvingIds[u.id]}>Delete</button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                                {tab === 'schools' && filteredUsers.map(u => (
                                    <tr key={u.id} style={u.payment_status !== 'paid' && u.screenshot_url ? { backgroundColor: '#FEF2F2' } : {}}>
                                        <td className="admin-text-bold">{u.school_name}</td>
                                        <td className="admin-text-muted">{u.admin_email}</td>
                                        <td><span className="admin-badge primary">School Admin</span></td>
                                        <td>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                                <span className={`admin-badge ${u.payment_status === 'paid' ? 'success' : 'warning'}`} style={{ width: 'fit-content' }}>
                                                    {u.payment_status === 'paid' ? 'Paid (Rs 5000)' : 'Pending'}
                                                </span>
                                                <span className="small text-muted" style={{ fontSize: '0.75rem' }}>
                                                    {u.status_changed_at ? `Changed: ${formatDate(u.status_changed_at)}` : `Created: ${formatDate(u.created_at)}`}
                                                </span>
                                                {u.payment_status === 'paid' && (
                                                    <span className="small text-success fw-bold" style={{ fontSize: '0.75rem' }}>
                                                        Lifetime Access
                                                    </span>
                                                )}
                                                {u.reminded_at && (
                                                    <span className="small text-danger" style={{ fontSize: '0.75rem', fontWeight: 'bold' }}>
                                                        Reminded: {formatDate(u.reminded_at)}
                                                    </span>
                                                )}
                                            </div>
                                        </td>
                                        <td>
                                            {u.screenshot_url ? (
                                                <a href={u.screenshot_url} target="_blank" rel="noreferrer" className="admin-btn admin-btn-sm admin-btn-primary" style={{ textDecoration: 'none', display: 'inline-block' }}>
                                                    View SS
                                                </a>
                                            ) : (
                                                <span className="text-muted small">None</span>
                                            )}
                                        </td>
                                        <td>
                                            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                                                {u.payment_status !== 'paid' ? (
                                                    <button className="admin-btn admin-btn-sm admin-btn-success" onClick={() => handleUpdateSchoolStatus(u.id, 'paid')} disabled={approvingIds[u.id]}>
                                                        {approvingIds[u.id] ? <FaSpinner className="fa-spin" /> : 'Approve'}
                                                    </button>
                                                ) : (
                                                    <button className="admin-btn admin-btn-sm admin-btn-warning" onClick={() => handleUpdateSchoolStatus(u.id, 'pending')} disabled={approvingIds[u.id]}>
                                                        {approvingIds[u.id] ? <FaSpinner className="fa-spin" /> : 'Reject'}
                                                    </button>
                                                )}
                                                <button className="admin-btn admin-btn-sm admin-btn-danger" onClick={() => handleDelete(u.id)} disabled={approvingIds[u.id]}>Delete</button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                </div>
            </div>
        </div>
    );
};

export default AdminUsers;
