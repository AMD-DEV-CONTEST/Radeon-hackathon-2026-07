import React, { useState, useEffect } from 'react';
import { supabase } from '../../../utils/supabaseClient';
import { parseTutorialDescription, generateSolutionXml } from '../../MagicStudio/tutorialEngine';

const AdminContent = () => {
    const [classes, setClasses] = useState([]);
    const [existingProjects, setExistingProjects] = useState([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [activeTab, setActiveTab] = useState('add');
    const [preview, setPreview] = useState(null);
    
    const [form, setForm] = useState({
        classLevel: '',
        lessonId: '',
        title: '',
        objective: '',
        steps: [{ id: 1, title: '', desc: '' }],
        orderIndex: 1,
        agentSolveDescription: '',
        agentSolveMessage: '',
        agentSolveTip: '',
        agentTutorialDescription: '',
        isPromptProject: false,
        perfectPrompt: '',
        promptMilestones: [{ id: 1, keyword: '', action: '' }]
    });

    useEffect(() => { fetchData(); }, []);

    const fetchData = async () => {
        setLoading(true);
        try {
            const timeout = (ms) => new Promise((_, rej) => setTimeout(() => rej(new Error('T')), ms));
            const fetchSafe = async (q) => {
                try { return await Promise.race([q, timeout(5000)]); } catch(e) { return { data: [] }; }
            };

            const [classesRes, lessonsRes] = await Promise.all([
                fetchSafe(supabase.from('course_classes').select('*').order('level', { ascending: true })),
                fetchSafe(supabase.from('lessons').select('*').order('order_index', { ascending: true }))
            ]);

            if (classesRes.data) setClasses(classesRes.data);
            if (lessonsRes.data) setExistingProjects(lessonsRes.data);
        } catch (err) {
            console.error("Error fetching data:", err);
        } finally {
            setLoading(false);
        }
    };

    // ── Project Steps ──
    const handleAddStep = () => {
        setForm(prev => ({
            ...prev,
            steps: [...prev.steps, { id: prev.steps.length + 1, title: '', desc: '' }]
        }));
    };
    const handleStepChange = (index, field, value) => {
        const newSteps = [...form.steps];
        newSteps[index][field] = value;
        setForm({ ...form, steps: newSteps });
    };
    const handleRemoveStep = (index) => {
        const reindexed = form.steps.filter((_, i) => i !== index).map((s, i) => ({ ...s, id: i + 1 }));
        setForm({ ...form, steps: reindexed });
    };

    // ── Prompt Milestones ──
    const handleAddMilestone = () => {
        setForm(prev => ({
            ...prev,
            promptMilestones: [...prev.promptMilestones, { id: prev.promptMilestones.length + 1, keyword: '', action: '' }]
        }));
    };
    const handleMilestoneChange = (index, field, value) => {
        const newMilestones = [...form.promptMilestones];
        newMilestones[index][field] = value;
        setForm({ ...form, promptMilestones: newMilestones });
    };

    // Preview parsed tutorial steps
    const handlePreview = () => {
        if (!form.agentTutorialDescription.trim()) {
            alert('Please enter a tutorial description first!');
            return;
        }
        try {
            const steps = parseTutorialDescription(form.agentTutorialDescription);
            setPreview(steps);
        } catch (err) {
            alert('Preview error: tutorialEngine may not be fully implemented yet.');
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSaving(true);
        try {
            // 1. Insert the lesson
            const lessonData = {
                id: form.lessonId,
                class_level: parseInt(form.classLevel),
                title: form.title,
                objective: form.objective,
                steps: form.steps,
                order_index: parseInt(form.orderIndex),
                is_prompt_project: form.isPromptProject,
                perfect_prompt: form.perfectPrompt,
                prompt_milestones: form.promptMilestones
            };
            const { error: lessonError } = await supabase.from('lessons').insert([lessonData]);
            if (lessonError) throw lessonError;

            // 2. Auto-generate solution XML from the description & insert tutor_solutions
            if (!form.isPromptProject) {
                const description = form.agentSolveDescription || form.agentTutorialDescription;
                let autoXml = null;
                try { autoXml = generateSolutionXml(description); } catch(e){}
                
                if (autoXml) {
                    const { error: solError } = await supabase.from('tutor_solutions').insert([{
                        lesson_id: form.lessonId,
                        message: form.agentSolveMessage || "Hi! I'm Kido. Let me show you how it's done!",
                        xml: autoXml,
                        tip: form.agentSolveTip || 'See? That was easy! Now try it yourself! 🌟'
                    }]);
                    if (solError) throw solError;
                }

                // 3. Store the tutorial description
                if (form.agentTutorialDescription.trim()) {
                    const { error: tutError } = await supabase.from('tutorial_steps').insert([{
                        lesson_id: form.lessonId,
                        step_index: 0,
                        message: form.agentTutorialDescription,
                        target_selector: null,
                        check_xml_contains: null,
                    }]);
                    if (tutError) throw tutError;
                }
            }

            alert('✅ Project added successfully!');

            setForm({
                classLevel: '', lessonId: '', title: '', objective: '',
                steps: [{ id: 1, title: '', desc: '' }], orderIndex: 1,
                agentSolveDescription: '', agentSolveMessage: '', agentSolveTip: '',
                agentTutorialDescription: '',
                isPromptProject: false,
                perfectPrompt: '',
                promptMilestones: [{ id: 1, keyword: '', action: '' }]
            });
            setPreview(null);
            fetchData();
        } catch (error) {
            console.error('Error adding project:', error);
            alert('❌ Failed: ' + error.message);
        } finally {
            setSaving(false);
        }
    };

    const handleDeleteProject = async (lessonId) => {
        if (!window.confirm(`Delete project "${lessonId}" and all agent data?`)) return;
        await supabase.from('tutorial_steps').delete().eq('lesson_id', lessonId);
        await supabase.from('tutor_solutions').delete().eq('lesson_id', lessonId);
        await supabase.from('lessons').delete().eq('id', lessonId);
        fetchData();
    };

    if (loading && classes.length === 0) return <div className="admin-text-muted" style={{ padding: '40px' }}>Initializing projects engine...</div>;

    return (
        <div>
            <div className="admin-page-header">
                <h2 className="admin-page-title">🛡️ Project & Agent Engine</h2>
                <p className="admin-page-desc">Add projects and train Kido agent — just describe what the tutorial should teach!</p>
            </div>

            {/* Tabs */}
            <div className="admin-tabs">
                <button className={`admin-tab ${activeTab === 'add' ? 'active' : ''}`} onClick={() => setActiveTab('add')}>
                    ➕ Add Project
                </button>
                <button className={`admin-tab ${activeTab === 'manage' ? 'active' : ''}`} onClick={() => setActiveTab('manage')}>
                    📋 Manage Projects ({existingProjects.length})
                </button>
            </div>

            {activeTab === 'manage' && (
                <div className="admin-card" style={{ padding: 0 }}>
                    {existingProjects.length === 0 ? (
                        <div style={{ padding: '40px', textAlign: 'center' }} className="admin-text-muted">No projects added yet.</div>
                    ) : (
                        <div className="admin-table-container">
                            <table className="admin-table">
                                <thead>
                                    <tr><th>ID</th><th>Title</th><th>Level</th><th>Order</th><th style={{textAlign:'right'}}>Actions</th></tr>
                                </thead>
                                <tbody>
                                    {existingProjects.map(l => (
                                        <tr key={l.id}>
                                            <td style={{ fontFamily: 'monospace', color: '#4F46E5' }}>{l.id}</td>
                                            <td className="admin-text-bold">{l.title}</td>
                                            <td>Level {l.class_level}</td>
                                            <td>{l.order_index}</td>
                                            <td>
                                                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                                                    <button className="admin-btn admin-btn-sm admin-btn-danger" onClick={() => handleDeleteProject(l.id)}>Delete</button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'add' && (
                <form onSubmit={handleSubmit}>
                    {/* SECTION 1: Project Info */}
                    <div className="admin-card" style={{ marginBottom: '24px' }}>
                        <h3 className="admin-kpi-label" style={{ fontSize: '1rem', marginBottom: '24px', color: '#0F172A' }}>📘 Project Information</h3>
                        
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '20px', marginBottom: '20px' }}>
                            <div className="admin-form-group" style={{ marginBottom: 0 }}>
                                <label className="admin-label">Select Level</label>
                                <select className="admin-select" value={form.classLevel} onChange={e => setForm({ ...form, classLevel: e.target.value })} required>
                                    <option value="">-- Select Level --</option>
                                    {classes.map(c => (<option key={c.id} value={c.level}>{c.title} ({c.level})</option>))}
                                </select>
                            </div>
                            <div className="admin-form-group" style={{ marginBottom: 0 }}>
                                <label className="admin-label">Project ID</label>
                                <input type="text" className="admin-input" placeholder="e.g. lesson-101" value={form.lessonId} onChange={e => setForm({ ...form, lessonId: e.target.value })} required />
                            </div>
                            <div className="admin-form-group" style={{ marginBottom: 0 }}>
                                <label className="admin-label">Order Index</label>
                                <input type="number" className="admin-input" value={form.orderIndex} onChange={e => setForm({ ...form, orderIndex: e.target.value })} required />
                            </div>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '20px', marginBottom: '32px' }}>
                            <div className="admin-form-group" style={{ marginBottom: 0 }}>
                                <label className="admin-label">Project Title</label>
                                <input type="text" className="admin-input" placeholder="e.g. 1. Move the Cat!" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} required />
                            </div>
                            <div className="admin-form-group" style={{ marginBottom: 0 }}>
                                <label className="admin-label">Objective</label>
                                <input type="text" className="admin-input" placeholder="e.g. Make the cat walk!" value={form.objective} onChange={e => setForm({ ...form, objective: e.target.value })} required />
                            </div>
                        </div>

                        <h4 className="admin-label" style={{ borderBottom: '1px solid #E2E8F0', paddingBottom: '8px', marginBottom: '16px' }}>Project Steps</h4>
                        {form.steps.map((step, index) => (
                            <div key={index} style={{ background: '#F8FAFC', padding: '16px', borderRadius: '12px', border: '1px solid #E2E8F0', marginBottom: '16px' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                                    <span className="admin-text-bold" style={{ fontSize: '0.85rem' }}>Step {step.id}</span>
                                    {form.steps.length > 1 && (
                                        <button type="button" className="admin-btn admin-btn-sm admin-btn-danger" style={{ padding: '2px 8px' }} onClick={() => handleRemoveStep(index)}>Remove</button>
                                    )}
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '16px' }}>
                                    <input type="text" className="admin-input" placeholder="Step Title" value={step.title} onChange={e => handleStepChange(index, 'title', e.target.value)} required />
                                    <input type="text" className="admin-input" placeholder="Step Description" value={step.desc} onChange={e => handleStepChange(index, 'desc', e.target.value)} required />
                                </div>
                            </div>
                        ))}
                        <button type="button" className="admin-btn admin-btn-secondary admin-btn-sm" onClick={handleAddStep}>+ Add Step</button>
                    </div>

                    {/* SECTION 2: Prompt Engineering Toggle */}
                    <div className="admin-card" style={{ marginBottom: '24px', borderLeft: '4px solid #10B981' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                            <h3 className="admin-kpi-label" style={{ fontSize: '1rem', margin: 0, color: '#0F172A' }}>✨ AI Sekkho: Prompt Engineering</h3>
                            <div className="form-check form-switch">
                                <input 
                                    className="form-check-input" 
                                    type="checkbox" 
                                    role="switch" 
                                    id="promptSwitch" 
                                    checked={form.isPromptProject}
                                    onChange={e => setForm({ ...form, isPromptProject: e.target.checked })}
                                />
                                <label className="form-check-label" htmlFor="promptSwitch" style={{ marginLeft: '10px', fontWeight: 'bold' }}>
                                    {form.isPromptProject ? 'Enabled' : 'Disabled'}
                                </label>
                            </div>
                        </div>

                        {form.isPromptProject && (
                            <div className="animate__animated animate__fadeIn">
                                <div className="admin-form-group">
                                    <label className="admin-label">🏆 The Perfect Prompt</label>
                                    <textarea 
                                        className="admin-textarea" 
                                        rows="3" 
                                        placeholder="Enter the ideal prompt that solves this project..."
                                        value={form.perfectPrompt}
                                        onChange={e => setForm({ ...form, perfectPrompt: e.target.value })}
                                    />
                                    <small className="text-muted">This is what the kids are aiming for!</small>
                                </div>

                                <h4 className="admin-label" style={{ borderBottom: '1px solid #E2E8F0', paddingBottom: '8px', marginTop: '24px', marginBottom: '16px' }}>
                                    🎯 Milestone Triggers (Step-by-Step)
                                </h4>
                                {form.promptMilestones.map((ms, index) => (
                                    <div key={index} style={{ background: '#F0FDF4', padding: '16px', borderRadius: '12px', border: '1px solid #DCFCE7', marginBottom: '16px' }}>
                                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '16px' }}>
                                            <div className="admin-form-group" style={{ marginBottom: 0 }}>
                                                <label className="admin-label">Keyword Trigger</label>
                                                <input 
                                                    type="text" 
                                                    className="admin-input" 
                                                    placeholder="e.g. bedroom" 
                                                    value={ms.keyword} 
                                                    onChange={e => handleMilestoneChange(index, 'keyword', e.target.value)} 
                                                />
                                            </div>
                                            <div className="admin-form-group" style={{ marginBottom: 0 }}>
                                                <label className="admin-label">Visual Action</label>
                                                <select 
                                                    className="admin-select" 
                                                    value={ms.action} 
                                                    onChange={e => handleMilestoneChange(index, 'action', e.target.value)}
                                                >
                                                    <option value="">-- Select Action --</option>
                                                    <option value="bg:bedroom">Set Background: Bedroom</option>
                                                    <option value="bg:jungle">Set Background: Jungle</option>
                                                    <option value="bg:space">Set Background: Space</option>
                                                    <option value="move:right">Move Sprite Right</option>
                                                    <option value="move:left">Move Sprite Left</option>
                                                    <option value="sound:play">Play Magic Sound</option>
                                                    <option value="sprite:show">Show Sprite</option>
                                                    <option value="sprite:hide">Hide Sprite</option>
                                                </select>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                                <button type="button" className="admin-btn admin-btn-secondary admin-btn-sm" onClick={handleAddMilestone}>+ Add Milestone</button>
                            </div>
                        )}
                    </div>

                    {!form.isPromptProject && (
                        <>
                            {/* SECTION 2: Simple Agent Training */}
                            <div className="admin-card" style={{ marginBottom: '24px', borderLeft: '4px solid #4F46E5' }}>
                                <h3 className="admin-kpi-label" style={{ fontSize: '1rem', marginBottom: '8px', color: '#0F172A', display: 'flex', alignItems: 'center' }}>
                                    🤖 Train Kido Agent <span className="admin-badge primary" style={{ marginLeft: '12px' }}>Smart Mode</span>
                                </h3>
                                <p className="admin-page-desc" style={{ fontSize: '0.85rem', marginBottom: '24px' }}>
                                    Just describe in simple words what blocks the child needs to use. Kido will automatically understand and create the visual tutorial with pointing hands!
                                </p>

                                <div className="admin-form-group">
                                    <label className="admin-label" style={{ color: '#0F172A' }}>📝 Tutorial Description <span style={{color: '#EF4444'}}>*</span></label>
                                    <textarea
                                        className="admin-textarea"
                                        rows="3"
                                        placeholder="Example: pick move 10 steps block, then click run"
                                        value={form.agentTutorialDescription}
                                        onChange={e => setForm({ ...form, agentTutorialDescription: e.target.value })}
                                    />
                                </div>

                                <button type="button" className="admin-btn admin-btn-secondary admin-btn-sm mb-4" onClick={handlePreview}>
                                    👁️ Preview Tutorial Steps
                                </button>

                                {preview && (
                                    <div style={{ background: '#F8FAFC', padding: '16px', borderRadius: '12px', border: '1px solid #E2E8F0', marginBottom: '24px' }}>
                                        <h6 className="admin-label" style={{ marginBottom: '12px' }}>🔍 Parsed Tutorial Steps ({preview.length} steps)</h6>
                                        {preview.map((step, i) => (
                                            <div key={i} style={{ display: 'flex', gap: '12px', marginBottom: '12px', padding: '12px', background: 'white', borderRadius: '8px', border: '1px solid #E2E8F0' }}>
                                                <span className="admin-badge primary" style={{ height: 'fit-content' }}>{i + 1}</span>
                                                <div>
                                                    <div className="admin-text-bold" style={{ color: '#4F46E5', fontSize: '0.75rem', textTransform: 'uppercase' }}>{step.action.replace(/_/g, ' ')}</div>
                                                    <div style={{ fontSize: '0.9rem', color: '#0F172A', marginTop: '4px' }}>{step.msg}</div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </>
                    )}

                    <button type="submit" className="admin-btn admin-btn-primary" style={{ width: '100%', padding: '16px', fontSize: '1.05rem' }} disabled={saving}>
                        {saving ? '⏳ Saving...' : '🚀 Save Project'}
                    </button>

                </form>
            )}
        </div>
    );
};

export default AdminContent;
