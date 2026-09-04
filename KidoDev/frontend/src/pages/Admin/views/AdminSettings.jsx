import React, { useState, useEffect } from 'react';
import { supabase } from '../../../utils/supabaseClient';
import { FaSpinner } from 'react-icons/fa';

const AdminSettings = () => {
    const [tab, setTab] = useState('schools'); // 'schools' or 'parents'
    const [loading, setLoading] = useState(true);
    const [schools, setSchools] = useState([]);
    const [parents, setParents] = useState([]);
    const [children, setChildren] = useState([]);
    const [search, setSearch] = useState('');
    const [expandedIds, setExpandedIds] = useState([]);
    const [selectedIds, setSelectedIds] = useState([]);
    const [approvingIds, setApprovingIds] = useState({});

    useEffect(() => {
        setSelectedIds([]);
        setExpandedIds([]);
        fetchUsers();
    }, [tab]);

    const fetchUsers = async () => {
        setLoading(true);
        try {
            const { data: schoolsData } = await supabase.from('schools').select('*').order('created_at', { ascending: false });
            const { data: parentsData } = await supabase.from('parent_profiles').select('*').order('created_at', { ascending: false });
            const { data: childrenData } = await supabase.from('children').select('*').order('created_at', { ascending: false });

            if (schoolsData) setSchools(schoolsData);
            if (parentsData) setParents(parentsData);
            if (childrenData) setChildren(childrenData);
        } catch (e) {
            console.error("Fetch error:", e);
        }
        setLoading(false);
    };

    const handleUpdateRole = async (table, id, newRole) => {
        try {
            const { error } = await supabase.from(table).update({ role: newRole }).eq('id', id);
            if (error) throw error;
            fetchUsers();
        } catch (err) {
            alert("Update role failed: " + err.message);
        }
    };

    const handleUpdateStatus = async (table, id, newStatus) => {
        setApprovingIds(prev => ({ ...prev, [id]: true }));
        try {
            const { error } = await supabase.from(table)
                .update({
                    payment_status: newStatus,
                    status_changed_at: new Date().toISOString()
                })
                .eq('id', id);
            if (error) throw error;
            await fetchUsers();
        } catch (err) {
            alert("Update status failed: " + err.message);
        } finally {
            setApprovingIds(prev => ({ ...prev, [id]: false }));
        }
    };

    const handleDelete = async (table, id) => {
        if (!window.confirm("Permanently delete this record?")) return;
        try {
            const { error } = await supabase.from(table).delete().eq('id', id);
            if (error) throw error;
            setSelectedIds(selectedIds.filter(x => x !== id));
            fetchUsers();
        } catch (err) {
            alert("Delete failed: " + err.message);
        }
    };

    const handleSelectRow = (id) => {
        if (selectedIds.includes(id)) {
            setSelectedIds(selectedIds.filter(x => x !== id));
        } else {
            setSelectedIds([...selectedIds, id]);
        }
    };

    const handleSelectAll = (items) => {
        if (selectedIds.length === items.length) {
            setSelectedIds([]);
        } else {
            setSelectedIds(items.map(r => r.id));
        }
    };

    const handleBulkStatus = async (newStatus) => {
        if (selectedIds.length === 0) return;
        setLoading(true);
        try {
            let table = tab === 'schools' ? 'schools' : 'parent_profiles';
            const { error } = await supabase.from(table)
                .update({
                    payment_status: newStatus,
                    status_changed_at: new Date().toISOString()
                })
                .in('id', selectedIds);
            if (error) throw error;
            setSelectedIds([]);
            fetchUsers();
        } catch (err) {
            alert("Bulk status update failed: " + err.message);
        }
        setLoading(false);
    };

    const handleBulkDelete = async () => {
        if (selectedIds.length === 0) return;
        if (!window.confirm(`Permanently delete the ${selectedIds.length} selected records?`)) return;
        setLoading(true);
        try {
            let table = tab === 'schools' ? 'schools' : 'parent_profiles';
            const { error } = await supabase.from(table).delete().in('id', selectedIds);
            if (error) throw error;
            setSelectedIds([]);
            fetchUsers();
        } catch (err) {
            alert("Bulk delete failed: " + err.message);
        }
        setLoading(false);
    };

    const toggleExpand = (id) => {
        if (expandedIds.includes(id)) {
            setExpandedIds(expandedIds.filter(x => x !== id));
        } else {
            setExpandedIds([...expandedIds, id]);
        }
    };

    // Filtered lists
    const filteredSchools = schools.filter(s => 
        (s.school_name || '').toLowerCase().includes(search.toLowerCase()) ||
        (s.admin_email || '').toLowerCase().includes(search.toLowerCase())
    );

    const filteredParents = parents.filter(p => 
        (p.full_name || '').toLowerCase().includes(search.toLowerCase()) ||
        (p.email || '').toLowerCase().includes(search.toLowerCase())
    );

    const formatDate = (isoStr) => {
        if (!isoStr) return '-';
        return new Date(isoStr).toLocaleString();
    };

    return (
        <div>
            <div className="admin-page-header admin-flex-between flex-wrap gap-3">
                <div>
                    <h1 className="admin-page-title">Access Control Center</h1>
                    <p className="admin-page-desc">Manage system roles, payments, and student link mappings</p>
                </div>
                <div className="d-flex gap-3 align-items-center">
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

            <div className="admin-tabs d-flex align-items-center justify-content-between flex-wrap gap-2">
                <div className="d-flex gap-1">
                    <button className={`admin-tab ${tab === 'schools' ? 'active' : ''}`} onClick={() => setTab('schools')}>
                        Schools &amp; Students
                    </button>
                    <button className={`admin-tab ${tab === 'parents' ? 'active' : ''}`} onClick={() => setTab('parents')}>
                        Parents &amp; Students
                    </button>
                </div>

                {selectedIds.length > 0 && (
                    <div className="d-flex gap-2 align-items-center bg-light p-2 rounded-4 border shadow-sm">
                        <span className="small fw-bold text-dark px-2">{selectedIds.length} Selected</span>
                        <button className="admin-btn admin-btn-sm admin-btn-success py-1 px-3" onClick={() => handleBulkStatus('paid')}>Bulk Approve</button>
                        <button className="admin-btn admin-btn-sm admin-btn-warning py-1 px-3" onClick={() => handleBulkStatus('pending')}>Bulk Reject</button>
                        <button className="admin-btn admin-btn-sm admin-btn-danger py-1 px-3" onClick={handleBulkDelete}>Bulk Delete</button>
                    </div>
                )}
            </div>

            <div className="admin-card" style={{ padding: 0 }}>
                <div className="admin-table-container">
                    <table className="admin-table">
                        {tab === 'schools' ? (
                            <>
                                <thead>
                                    <tr>
                                        <th style={{ width: '40px' }}>
                                            <input 
                                                type="checkbox" 
                                                checked={filteredSchools.length > 0 && selectedIds.length === filteredSchools.length}
                                                onChange={() => handleSelectAll(filteredSchools)}
                                            />
                                        </th>
                                        <th>School Name</th>
                                        <th>Admin Email</th>
                                        <th>Role Permissions</th>
                                        <th>Payment Status</th>
                                        <th>Proof (Screenshot)</th>
                                        <th style={{ textAlign: 'right' }}>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {loading && filteredSchools.length === 0 && (
                                        <tr><td colSpan="7" style={{ textAlign: 'center', padding: '40px', color: '#64748B' }}>Fetching records...</td></tr>
                                    )}
                                    {!loading && filteredSchools.length === 0 && (
                                        <tr><td colSpan="7" style={{ textAlign: 'center', padding: '40px', color: '#64748B' }}>No school records found.</td></tr>
                                    )}
                                    {filteredSchools.map(u => {
                                        const schoolKids = children.filter(c => c.school_id === u.id);
                                        const isExpanded = expandedIds.includes(u.id);
                                        const schoolNeedsAction = (u.payment_status !== 'paid' && u.screenshot_url) || schoolKids.some(k => k.payment_status !== 'paid' && k.screenshot_url);
                                        return (
                                            <React.Fragment key={u.id}>
                                                <tr 
                                                    className={selectedIds.includes(u.id) ? 'bg-light' : ''}
                                                    style={schoolNeedsAction ? { backgroundColor: '#FEF2F2', fontWeight: 'bold' } : {}}
                                                >
                                                    <td>
                                                        <input 
                                                            type="checkbox" 
                                                            checked={selectedIds.includes(u.id)} 
                                                            onChange={() => handleSelectRow(u.id)}
                                                        />
                                                    </td>
                                                    <td className="admin-text-bold">
                                                        <button 
                                                            className="btn btn-link text-decoration-none p-0 fw-black text-dark me-2 small"
                                                            onClick={() => toggleExpand(u.id)}
                                                            style={{ fontSize: '0.85rem' }}
                                                        >
                                                            {isExpanded ? '▼' : '▶'}
                                                        </button>
                                                        {u.school_name}
                                                        <span className="badge bg-light text-muted border ms-2 small" style={{ fontSize: '0.7rem' }}>
                                                            {schoolKids.length} Students
                                                        </span>
                                                        {schoolNeedsAction && (
                                                            <span className="admin-badge danger ms-2" style={{ fontSize: '0.7rem' }}>Action Needed</span>
                                                        )}
                                                    </td>
                                                    <td className="admin-text-muted">{u.admin_email}</td>
                                                    <td>
                                                        <select 
                                                            className="form-select form-select-sm rounded-pill px-3 py-1"
                                                            value={u.role || 'school_admin'} 
                                                            onChange={(e) => handleUpdateRole('schools', u.id, e.target.value)}
                                                            style={{ width: '140px', fontSize: '0.82rem' }}
                                                        >
                                                            <option value="school_admin">School Admin</option>
                                                            <option value="partner">Partner</option>
                                                            <option value="admin">Admin</option>
                                                        </select>
                                                    </td>
                                                    <td>
                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                                            <span className={`admin-badge ${u.payment_status === 'paid' ? 'success' : 'warning'}`} style={{ width: 'fit-content' }}>
                                                                {u.payment_status === 'paid' ? 'Paid' : 'Unpaid'}
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
                                                                <button className="admin-btn admin-btn-sm admin-btn-success" onClick={() => handleUpdateStatus('schools', u.id, 'paid')} disabled={approvingIds[u.id]}>
                                                                    {approvingIds[u.id] ? <FaSpinner className="fa-spin" /> : 'Approve'}
                                                                </button>
                                                            ) : (
                                                                <button className="admin-btn admin-btn-sm admin-btn-warning" onClick={() => handleUpdateStatus('schools', u.id, 'pending')} disabled={approvingIds[u.id]}>
                                                                    {approvingIds[u.id] ? <FaSpinner className="fa-spin" /> : 'Reject'}
                                                                </button>
                                                            )}
                                                            <button className="admin-btn admin-btn-sm admin-btn-danger" onClick={() => handleDelete('schools', u.id)} disabled={approvingIds[u.id]}>Delete</button>
                                                        </div>
                                                    </td>
                                                </tr>
                                                {isExpanded && (
                                                    <tr>
                                                        <td colSpan="7" className="bg-light p-3 border-top-0">
                                                            <div className="card rounded-4 border p-3 bg-white">
                                                                <div className="fw-black text-muted mb-2 small text-uppercase" style={{ fontSize: '0.75rem' }}>Roster Students ({schoolKids.length})</div>
                                                                {schoolKids.length === 0 ? (
                                                                    <div className="text-muted small italic">No students registered in this school roster.</div>
                                                                ) : (
                                                                    <table className="table align-middle mb-0 small">
                                                                        <thead>
                                                                            <tr>
                                                                                <th>Student Name</th>
                                                                                <th>Secret Key</th>
                                                                                <th>Grade</th>
                                                                                <th>Payment Status</th>
                                                                                <th>Screenshot</th>
                                                                                <th style={{ textAlign: 'right' }}>Actions</th>
                                                                            </tr>
                                                                        </thead>
                                                                        <tbody>
                                                                            {schoolKids.map(k => (
                                                                                <tr key={k.id} style={k.payment_status !== 'paid' && k.screenshot_url ? { backgroundColor: '#FEF2F2' } : {}}>
                                                                                    <td className="fw-bold">{k.name}</td>
                                                                                    <td className="font-monospace text-primary">{k.secret_key}</td>
                                                                                    <td>{k.current_level}</td>
                                                                                    <td>
                                                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                                                                            <span className={`admin-badge ${k.payment_status === 'paid' ? 'success' : 'warning'}`}>
                                                                                                {k.payment_status === 'paid' ? 'Active' : 'Unpaid'}
                                                                                            </span>
                                                                                            {k.payment_status === 'paid' && (
                                                                                                <span className="small text-danger fw-bold" style={{ fontSize: '0.7rem' }}>
                                                                                                    Expiry: {formatDate(new Date(new Date(k.status_changed_at || k.created_at).getTime() + 30 * 24 * 60 * 60 * 1000).toISOString())}
                                                                                                </span>
                                                                                            )}
                                                                                        </div>
                                                                                    </td>
                                                                                    <td>
                                                                                        {k.screenshot_url ? (
                                                                                            <a href={k.screenshot_url} target="_blank" rel="noreferrer" className="btn btn-outline-primary btn-sm rounded-pill py-0 px-3 small" style={{ fontSize: '0.75rem' }}>View SS</a>
                                                                                        ) : <span className="text-muted">None</span>}
                                                                                    </td>
                                                                                    <td style={{ textAlign: 'right' }}>
                                                                                        <div className="d-flex gap-2 justify-content-end">
                                                                                            {k.payment_status !== 'paid' ? (
                                                                                                <button className="btn btn-success btn-sm rounded-pill py-0 px-2 small" onClick={() => handleUpdateStatus('children', k.id, 'paid')} disabled={approvingIds[k.id]}>
                                                                                                    {approvingIds[k.id] ? <FaSpinner className="fa-spin" /> : 'Approve'}
                                                                                                </button>
                                                                                            ) : (
                                                                                                <button className="btn btn-warning btn-sm rounded-pill py-0 px-2 small" onClick={() => handleUpdateStatus('children', k.id, 'pending')} disabled={approvingIds[k.id]}>
                                                                                                    {approvingIds[k.id] ? <FaSpinner className="fa-spin" /> : 'Reject'}
                                                                                                </button>
                                                                                            )}
                                                                                            <button className="btn btn-danger btn-sm rounded-pill py-0 px-2 small" onClick={() => handleDelete('children', k.id)} disabled={approvingIds[k.id]}>Delete</button>
                                                                                        </div>
                                                                                    </td>
                                                                                </tr>
                                                                            ))}
                                                                        </tbody>
                                                                    </table>
                                                                )}
                                                            </div>
                                                        </td>
                                                    </tr>
                                                )}
                                            </React.Fragment>
                                        );
                                    })}
                                </tbody>
                            </>
                        ) : (
                            <>
                                <thead>
                                    <tr>
                                        <th style={{ width: '40px' }}>
                                            <input 
                                                type="checkbox" 
                                                checked={filteredParents.length > 0 && selectedIds.length === filteredParents.length}
                                                onChange={() => handleSelectAll(filteredParents)}
                                            />
                                        </th>
                                        <th>Parent Name</th>
                                        <th>Email Address</th>
                                        <th>CNIC</th>
                                        <th>Role Permissions</th>
                                        <th style={{ textAlign: 'right' }}>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {loading && filteredParents.length === 0 && (
                                        <tr><td colSpan="6" style={{ textAlign: 'center', padding: '40px', color: '#64748B' }}>Fetching records...</td></tr>
                                    )}
                                    {!loading && filteredParents.length === 0 && (
                                        <tr><td colSpan="6" style={{ textAlign: 'center', padding: '40px', color: '#64748B' }}>No parent records found.</td></tr>
                                    )}
                                    {filteredParents.map(u => {
                                        const parentKids = children.filter(c => c.parent_id === u.id);
                                        const isExpanded = expandedIds.includes(u.id);
                                        const parentNeedsAction = parentKids.some(k => k.payment_status !== 'paid' && k.screenshot_url);
                                        return (
                                            <React.Fragment key={u.id}>
                                                <tr 
                                                    className={selectedIds.includes(u.id) ? 'bg-light' : ''}
                                                    style={parentNeedsAction ? { backgroundColor: '#FEF2F2', fontWeight: 'bold' } : {}}
                                                >
                                                    <td>
                                                        <input 
                                                            type="checkbox" 
                                                            checked={selectedIds.includes(u.id)} 
                                                            onChange={() => handleSelectRow(u.id)}
                                                        />
                                                    </td>
                                                    <td className="admin-text-bold">
                                                        <button 
                                                            className="btn btn-link text-decoration-none p-0 fw-black text-dark me-2 small"
                                                            onClick={() => toggleExpand(u.id)}
                                                            style={{ fontSize: '0.85rem' }}
                                                        >
                                                            {isExpanded ? '▼' : '▶'}
                                                        </button>
                                                        {u.full_name || 'N/A'}
                                                        <span className="badge bg-light text-muted border ms-2 small" style={{ fontSize: '0.7rem' }}>
                                                            {parentKids.length} Children
                                                        </span>
                                                        {parentNeedsAction && (
                                                            <span className="admin-badge danger ms-2" style={{ fontSize: '0.7rem' }}>Action Needed</span>
                                                        )}
                                                    </td>
                                                    <td className="admin-text-muted">{u.email}</td>
                                                    <td className="font-monospace text-muted">{u.cnic || '-'}</td>
                                                    <td>
                                                        <select 
                                                            className="form-select form-select-sm rounded-pill px-3 py-1"
                                                            value={u.role || 'parent'} 
                                                            onChange={(e) => handleUpdateRole('parent_profiles', u.id, e.target.value)}
                                                            style={{ width: '120px', fontSize: '0.82rem' }}
                                                        >
                                                            <option value="parent">Parent</option>
                                                            <option value="partner">Partner</option>
                                                            <option value="admin">Admin</option>
                                                        </select>
                                                    </td>
                                                    <td>
                                                        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                                                            <button className="admin-btn admin-btn-sm admin-btn-danger" onClick={() => handleDelete('parent_profiles', u.id)}>Delete</button>
                                                        </div>
                                                    </td>
                                                </tr>
                                                {isExpanded && (
                                                    <tr>
                                                        <td colSpan="6" className="bg-light p-3 border-top-0">
                                                            <div className="card rounded-4 border p-3 bg-white">
                                                                <div className="fw-black text-muted mb-2 small text-uppercase" style={{ fontSize: '0.75rem' }}>Parent Linked Children ({parentKids.length})</div>
                                                                {parentKids.length === 0 ? (
                                                                    <div className="text-muted small italic">No child profiles registered directly by this parent.</div>
                                                                ) : (
                                                                    <table className="table align-middle mb-0 small">
                                                                        <thead>
                                                                            <tr>
                                                                                <th>Child Name</th>
                                                                                <th>Secret Key</th>
                                                                                <th>Class Grade</th>
                                                                                <th>Payment Status</th>
                                                                                <th>Screenshot</th>
                                                                                <th style={{ textAlign: 'right' }}>Actions</th>
                                                                            </tr>
                                                                        </thead>
                                                                        <tbody>
                                                                            {parentKids.map(k => (
                                                                                <tr key={k.id} style={k.payment_status !== 'paid' && k.screenshot_url ? { backgroundColor: '#FEF2F2' } : {}}>
                                                                                    <td className="fw-bold">{k.name}</td>
                                                                                    <td className="font-monospace text-primary">{k.secret_key}</td>
                                                                                    <td>{k.current_level}</td>
                                                                                    <td>
                                                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                                                                            <span className={`admin-badge ${k.payment_status === 'paid' ? 'success' : 'warning'}`}>
                                                                                                {k.payment_status === 'paid' ? 'Active' : 'Unpaid'}
                                                                                            </span>
                                                                                            {k.payment_status === 'paid' && (
                                                                                                <span className="small text-danger fw-bold" style={{ fontSize: '0.7rem' }}>
                                                                                                    Expiry: {formatDate(new Date(new Date(k.status_changed_at || k.created_at).getTime() + 30 * 24 * 60 * 60 * 1000).toISOString())}
                                                                                                </span>
                                                                                            )}
                                                                                        </div>
                                                                                    </td>
                                                                                    <td>
                                                                                        {k.screenshot_url ? (
                                                                                            <a href={k.screenshot_url} target="_blank" rel="noreferrer" className="btn btn-outline-primary btn-sm rounded-pill py-0 px-3 small" style={{ fontSize: '0.75rem' }}>View SS</a>
                                                                                        ) : <span className="text-muted">None</span>}
                                                                                    </td>
                                                                                    <td style={{ textAlign: 'right' }}>
                                                                                        <div className="d-flex gap-2 justify-content-end">
                                                                                            {k.payment_status !== 'paid' ? (
                                                                                                <button className="btn btn-success btn-sm rounded-pill py-0 px-2 small" onClick={() => handleUpdateStatus('children', k.id, 'paid')} disabled={approvingIds[k.id]}>
                                                                                                    {approvingIds[k.id] ? <FaSpinner className="fa-spin" /> : 'Approve'}
                                                                                                </button>
                                                                                            ) : (
                                                                                                <button className="btn btn-warning btn-sm rounded-pill py-0 px-2 small" onClick={() => handleUpdateStatus('children', k.id, 'pending')} disabled={approvingIds[k.id]}>
                                                                                                    {approvingIds[k.id] ? <FaSpinner className="fa-spin" /> : 'Reject'}
                                                                                                </button>
                                                                                            )}
                                                                                            <button className="btn btn-danger btn-sm rounded-pill py-0 px-2 small" onClick={() => handleDelete('children', k.id)} disabled={approvingIds[k.id]}>Delete</button>
                                                                                        </div>
                                                                                    </td>
                                                                                </tr>
                                                                            ))}
                                                                        </tbody>
                                                                    </table>
                                                                )}
                                                            </div>
                                                        </td>
                                                    </tr>
                                                )}
                                            </React.Fragment>
                                        );
                                    })}
                                </tbody>
                            </>
                        )}
                    </table>
                </div>
            </div>
        </div>
    );
};

export default AdminSettings;
