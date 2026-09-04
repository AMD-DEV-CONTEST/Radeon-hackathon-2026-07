import React, { useState, useEffect } from 'react';
import { supabase } from '../../../utils/supabaseClient';

const AdminContentManage = () => {
    const [contentList, setContentList] = useState([]);
    const [loading, setLoading] = useState(true);
    const [editingItem, setEditingItem] = useState(null);
    const [editForm, setEditForm] = useState({ title: '', video_url: '', description: '' });

    useEffect(() => { fetchContent(); }, []);

    const fetchContent = async () => {
        setLoading(true);
        // Using 'content_library' as per previous architecture instructions
        const { data } = await supabase.from('content_library').select('*').order('created_at', { ascending: false });
        if (data) setContentList(data);
        setLoading(false);
    };

    const handleDelete = async (id) => {
        if (!window.confirm('Delete this library resource permanently?')) return;
        await supabase.from('content_library').delete().eq('id', id);
        fetchContent();
    };

    const handleEditClick = (item) => {
        setEditingItem(item.id);
        setEditForm({ title: item.title, video_url: item.video_url, description: item.description });
    };

    const handleSaveEdit = async () => {
        await supabase.from('content_library').update(editForm).eq('id', editingItem);
        setEditingItem(null);
        fetchContent();
    };

    return (
        <div>
            <div className="admin-page-header">
                <h1 className="admin-page-title">Content Library</h1>
                <p className="admin-page-desc">Manage existing educational resources and videos</p>
            </div>

            <div className="admin-card" style={{ padding: 0 }}>
                <div className="admin-table-container">
                    {loading ? (
                        <div style={{ padding: '40px', textAlign: 'center', color: '#64748B' }}>Loading library...</div>
                    ) : (
                        <table className="admin-table">
                            <thead>
                                <tr>
                                    <th style={{ width: '30%' }}>Title</th>
                                    <th style={{ width: '40%' }}>Description</th>
                                    <th style={{ width: '15%' }}>Type / URL</th>
                                    <th style={{ width: '15%', textAlign: 'right' }}>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {contentList.length === 0 && (
                                    <tr><td colSpan="4" style={{ textAlign: 'center', padding: '40px', color: '#64748B' }}>Library is empty. Publish content first.</td></tr>
                                )}
                                {contentList.map(item => (
                                    <tr key={item.id}>
                                        {editingItem === item.id ? (
                                            <>
                                                <td><input className="admin-input" value={editForm.title} onChange={e => setEditForm({...editForm, title: e.target.value})} /></td>
                                                <td><textarea className="admin-textarea" rows="2" value={editForm.description} onChange={e => setEditForm({...editForm, description: e.target.value})}></textarea></td>
                                                <td><input className="admin-input" value={editForm.video_url} onChange={e => setEditForm({...editForm, video_url: e.target.value})} /></td>
                                                <td>
                                                    <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                                                        <button className="admin-btn admin-btn-sm admin-btn-primary" onClick={handleSaveEdit}>Save</button>
                                                        <button className="admin-btn admin-btn-sm admin-btn-secondary" onClick={() => setEditingItem(null)}>Cancel</button>
                                                    </div>
                                                </td>
                                            </>
                                        ) : (
                                            <>
                                                <td className="admin-text-bold">{item.title}</td>
                                                <td className="admin-text-muted" style={{ fontSize: '0.85rem' }}>{item.description}</td>
                                                <td>
                                                    {item.video_url ? (
                                                        <a href={item.video_url} target="_blank" rel="noreferrer" style={{ color: '#4F46E5', textDecoration: 'none', fontSize: '0.85rem' }}>View Link</a>
                                                    ) : <span className="admin-text-muted">No URL</span>}
                                                </td>
                                                <td>
                                                    <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                                                        <button className="admin-btn admin-btn-sm admin-btn-secondary" onClick={() => handleEditClick(item)}>Edit</button>
                                                        <button className="admin-btn admin-btn-sm admin-btn-danger" onClick={() => handleDelete(item.id)}>Delete</button>
                                                    </div>
                                                </td>
                                            </>
                                        )}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            </div>
        </div>
    );
};

export default AdminContentManage;
