import React, { useState, useEffect } from 'react';
import { supabase } from '../../../utils/supabaseClient';
import Papa from 'papaparse';
import { FaUpload, FaDownload, FaEdit, FaTrash, FaCheckCircle, FaExclamationTriangle, FaMagic, FaBook, FaRobot, FaCogs, FaBookOpen } from 'react-icons/fa';
import SpriteLoader from '../../../components/Loader/SpriteLoader';
import { parseTutorialDescription, generateSolutionXml } from '../../MagicStudio/tutorialEngine';
import { generateFullProject } from '../../../utils/aiClient';

const AdminProjectManager = () => {
    const [lessons, setLessons] = useState([]);
    const [classes, setClasses] = useState([]);
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const [activeTab, setActiveTab] = useState('list'); // 'list', 'bulk', 'edit'
    const [editingProject, setEditingProject] = useState(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [msg, setMsg] = useState(null);
    const [selectedIds, setSelectedIds] = useState([]);
    const [csvText, setCsvText] = useState('');
    const [synthesisLogs, setSynthesisLogs] = useState([]);
    
    // Auto-generate state
    const [aiPrompt, setAiPrompt] = useState('');
    const [isGenerating, setIsGenerating] = useState(false);

    // Form state for Add/Edit
    const [form, setForm] = useState({
        id: '',
        title: '',
        objective: '',
        class_level: 1,
        order_index: 1,
        is_prompt_project: false,
        perfect_prompt: '',
        steps: [],
        prompt_milestones: [],
        agent_solve_description: '',
        agent_solve_message: '',
        agent_solve_tip: '',
        agent_tutorial_description: ''
    });

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        setLoading(true);
        try {
            const { data, error } = await supabase
                .from('lessons')
                .select('*, tutor_solutions(*), tutorial_steps(*)')
                .order('class_level', { ascending: true })
                .order('order_index', { ascending: true });

            if (error) throw error;
            setLessons(data || []);
        } catch (err) {
            setMsg({ type: 'error', text: "Failed to sync with Kido database" });
        } finally {
            setLoading(false);
        }
    };

    const safeJsonParse = (str, fallback = []) => {
        if (!str || str === '""' || str === "''") return fallback;
        try {
            return JSON.parse(str);
        } catch (e) {
            try {
                const fixed = str.replace(/'/g, '"');
                return JSON.parse(fixed);
            } catch (e2) {
                if (typeof str === 'string' && str.length > 0) {
                    return [{ title: "Instructions", desc: str }];
                }
                return fallback;
            }
        }
    };

    const handleProcessCSV = async (data) => {
        setUploading(true);
        setUploadProgress(10);
        setSynthesisLogs([]);
        setMsg({ type: 'info', text: "🤖 Kido Agent is starting the Deep Synthesis process..." });

        const total = data.length;
        
        try {
            for (let i = 0; i < total; i++) {
                const row = data[i];
                if (!row.id) continue;

                const progress = Math.round(10 + ((i / total) * 90));
                setUploadProgress(progress);

                const levelMatch = row.class_level?.toString().match(/\d+/);
                const classLevel = levelMatch ? parseInt(levelMatch[0]) : 1;

                const projectData = {
                    id: row.id.trim(),
                    title: row.title?.trim() || 'Untitled Project',
                    objective: row.objective?.trim() || '',
                    class_level: classLevel,
                    order_index: parseInt(row.order_index) || (i + 1),
                    is_prompt_project: row.is_prompt_project?.toLowerCase() === 'true',
                    perfect_prompt: row.perfect_prompt || '',
                    steps: safeJsonParse(row.steps, []),
                    prompt_milestones: safeJsonParse(row.prompt_milestones, [])
                };

                const logEntry = { id: projectData.id, status: 'processing', details: 'Synthesizing agent logic...' };
                setSynthesisLogs(prev => [...prev, logEntry]);

                await supabase.from('lessons').upsert([projectData]);

                if (!projectData.is_prompt_project) {
                    const solveDesc = row.agent_solve_description || row.agent_tutorial_description;
                    const tutorialDesc = row.agent_tutorial_description;

                    if (solveDesc) {
                        const xml = generateSolutionXml(solveDesc);
                        if (xml) {
                            await supabase.from('tutor_solutions').upsert([{
                                lesson_id: projectData.id,
                                message: row.agent_solve_message || "Let's build this together!",
                                xml: xml,
                                tip: row.agent_solve_tip || "Check the order of your blocks!"
                            }]);
                        }
                    }

                    if (tutorialDesc) {
                        const guideSteps = parseTutorialDescription(tutorialDesc);
                        if (guideSteps.length > 0) {
                            await supabase.from('tutorial_steps').delete().eq('lesson_id', projectData.id);
                            const stepsToInsert = guideSteps.map((s, idx) => ({
                                lesson_id: projectData.id,
                                step_index: idx,
                                message: s.msg,
                                target_selector: s.target || null,
                                check_xml_contains: s.checkValue || null
                            }));
                            await supabase.from('tutorial_steps').insert(stepsToInsert);
                        }
                    }
                }

                setSynthesisLogs(prev => prev.map(l => l.id === projectData.id ? { ...l, status: 'complete', details: `Synthesized with ${projectData.steps.length} steps.` } : l));
            }

            setUploadProgress(100);
            setMsg({ type: 'success', text: `✨ Heart of the project updated! ${total} projects perfectly synthesized.` });
            fetchData();
            setTimeout(() => setActiveTab('list'), 3000);
        } catch (err) {
            setMsg({ type: 'error', text: `Synthesis Interrupted: ${err.message}` });
            console.error(err);
        } finally {
            setUploading(false);
        }
    };

    const handleFileUpload = (e) => {
        const file = e.target.files[0];
        if (!file) return;
        Papa.parse(file, {
            header: true,
            skipEmptyLines: true,
            complete: (results) => handleProcessCSV(results.data)
        });
    };

    const handlePasteSubmit = () => {
        if (!csvText.trim()) return;
        Papa.parse(csvText, {
            header: true,
            skipEmptyLines: true,
            complete: (results) => handleProcessCSV(results.data)
        });
    };

    const handleDelete = async (id) => {
        if (!window.confirm("Are you sure you want to delete this project? This will also clear its agent training and student progress.")) return;
        setLoading(true);
        try {
            await supabase.from('tutorial_steps').delete().eq('lesson_id', id);
            await supabase.from('tutor_solutions').delete().eq('lesson_id', id);
            await supabase.from('projects').delete().eq('lesson_id', id);
            
            const { error } = await supabase.from('lessons').delete().eq('id', id);
            if (error) throw error;

            setMsg({ type: 'success', text: "Project and all related data deleted successfully" });
            fetchData();
        } catch (err) {
            setMsg({ type: 'error', text: `Delete failed: ${err.message}` });
        } finally {
            setLoading(false);
        }
    };

    const handleEdit = (project) => {
        const solution = project.tutor_solutions?.[0] || {};
        const tutorial = project.tutorial_steps?.length > 0 ? project.tutorial_steps[0].message : '';
        
        setEditingProject(project);
        setForm({
            id: project.id,
            title: project.title,
            objective: project.objective,
            class_level: project.class_level,
            order_index: project.order_index,
            is_prompt_project: project.is_prompt_project,
            perfect_prompt: project.perfect_prompt || '',
            steps: project.steps || [],
            prompt_milestones: project.prompt_milestones || [],
            agent_solve_description: project.objective,
            agent_solve_message: solution.message || '',
            agent_solve_tip: solution.tip || '',
            agent_tutorial_description: tutorial || ''
        });
        setActiveTab('edit');
    };

    const handleToggleSelect = (id) => {
        setSelectedIds(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]);
    };

    const handleSelectAll = () => {
        if (selectedIds.length === filteredLessons.length) {
            setSelectedIds([]);
        } else {
            setSelectedIds(filteredLessons.map(l => l.id));
        }
    };

    const handleBulkDelete = async () => {
        if (!selectedIds.length) return;
        if (!window.confirm(`Are you sure you want to delete ${selectedIds.length} projects? This will also clear all related agent training and student progress data.`)) return;

        setLoading(true);
        try {
            await supabase.from('tutorial_steps').delete().in('lesson_id', selectedIds);
            await supabase.from('tutor_solutions').delete().in('lesson_id', selectedIds);
            await supabase.from('projects').delete().in('lesson_id', selectedIds);

            const { error } = await supabase.from('lessons').delete().in('id', selectedIds);
            if (error) throw error;

            setMsg({ type: 'success', text: `Successfully purged ${selectedIds.length} projects and their ecosystems.` });
            setSelectedIds([]);
            fetchData();
        } catch (err) {
            setMsg({ type: 'error', text: `Bulk delete failed: ${err.message}` });
        } finally {
            setLoading(false);
        }
    };

    const handleMagicSynthesis = async () => {
        if (!aiPrompt.trim()) {
            setMsg({ type: 'error', text: "Please enter a prompt to generate the project!" });
            return;
        }

        setIsGenerating(true);
        setMsg({ type: 'info', text: "Processing... Generating full project structure." });
        
        try {
            const data = await generateFullProject(aiPrompt);
            
            setForm(prev => ({
                ...prev,
                id: data.id || prev.id || `P${Math.floor(Math.random() * 1000)}`,
                title: data.title || prev.title,
                objective: data.objective || prev.objective,
                class_level: data.class_level || prev.class_level,
                order_index: data.order_index || prev.order_index,
                agent_solve_description: data.agent_solve_description || '',
                agent_solve_message: data.agent_solve_message || '',
                agent_solve_tip: data.agent_solve_tip || '',
                agent_tutorial_description: data.agent_tutorial_description || '',
                steps: data.steps || [],
                prompt_milestones: data.prompt_milestones || []
            }));

            setMsg({ type: 'success', text: "AI Synthesis Complete! All fields auto-filled." });
        } catch (err) {
            setMsg({ type: 'error', text: `AI Synthesis Failed: ${err.message}` });
        } finally {
            setIsGenerating(false);
        }
    };

    const handleSave = async (e) => {
        e.preventDefault();
        setUploading(true);
        try {
            const lessonData = {
                id: form.id,
                title: form.title,
                objective: form.objective,
                class_level: form.class_level,
                order_index: form.order_index,
                is_prompt_project: form.is_prompt_project,
                perfect_prompt: form.perfect_prompt,
                steps: form.steps,
                prompt_milestones: form.prompt_milestones
            };
            const { error: lErr } = await supabase.from('lessons').upsert([lessonData]);
            if (lErr) throw lErr;

            if (!form.is_prompt_project) {
                const solveDesc = form.agent_solve_description || form.objective;
                if (solveDesc) {
                    // Use AI-generated XML if available, otherwise fallback to regex
                    let xml = editingProject?.generatedXml || generateSolutionXml(solveDesc);
                    
                    if (xml) {
                        await supabase.from('tutor_solutions').upsert([{
                            lesson_id: form.id,
                            message: form.agent_solve_message || "Great work!",
                            xml: xml,
                            tip: form.agent_solve_tip || "Try checking the order."
                        }]);
                    }
                }

                if (form.agent_tutorial_description) {
                    const guideSteps = parseTutorialDescription(form.agent_tutorial_description);
                    if (guideSteps.length > 0) {
                        await supabase.from('tutorial_steps').delete().eq('lesson_id', form.id);
                        const stepsToInsert = guideSteps.map((s, idx) => ({
                            lesson_id: form.id,
                            step_index: idx,
                            message: s.msg,
                            target_selector: s.target || null,
                            check_xml_contains: s.checkValue || null
                        }));
                        await supabase.from('tutorial_steps').insert(stepsToInsert);
                    }
                }
            }

            setMsg({ type: 'success', text: "Project and Agent logic updated successfully!" });
            fetchData();
            setActiveTab('list');
        } catch (err) {
            setMsg({ type: 'error', text: `Synthesis failed: ${err.message}` });
        } finally {
            setUploading(false);
        }
    };

    const filteredLessons = lessons.filter(l => 
        l.title?.toLowerCase().includes(searchQuery.toLowerCase()) || 
        l.id?.toLowerCase().includes(searchQuery.toLowerCase())
    );

    if (loading) return (
        <div style={{height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#F8FAFC'}}>
            <SpriteLoader />
        </div>
    );

    return (
        <div className="apm-container">
            <div className="apm-header">
                <div>
                    <h1 className="apm-title">Project Command Center</h1>
                    <p className="apm-subtitle">Bulk manage, edit, and orchestrate learning projects</p>
                </div>
                <div className="apm-actions">
                    <button className={`apm-tab-btn ${activeTab === 'list' ? 'active' : ''}`} onClick={() => setActiveTab('list')}>
                        <FaBook /> All Projects
                    </button>
                    <button className={`apm-tab-btn ${activeTab === 'bulk' ? 'active' : ''}`} onClick={() => setActiveTab('bulk')}>
                        <FaUpload /> Bulk Upload
                    </button>
                    <button className="apm-btn-primary" onClick={() => {
                        setForm({ id: '', title: '', objective: '', class_level: 1, order_index: 1, is_prompt_project: false, perfect_prompt: '', steps: [], prompt_milestones: [], agent_solve_description: '', agent_solve_message: '', agent_solve_tip: '', agent_tutorial_description: '' });
                        setActiveTab('edit');
                    }}>
                        + New Project
                    </button>
                </div>
            </div>

            {msg && (
                <div className={`apm-alert ${msg.type}`}>
                    {msg.type === 'success' ? <FaCheckCircle /> : <FaExclamationTriangle />}
                    {msg.text}
                    <button onClick={() => setMsg(null)} className="apm-alert-close">&times;</button>
                </div>
            )}

            {activeTab === 'list' && (
                <div className="apm-card">
                    <div className="apm-table-tools">
                        <div className="apm-search-wrapper">
                            <input 
                                type="text" 
                                className="apm-search" 
                                placeholder="Search projects..." 
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                            />
                        </div>
                        {selectedIds.length > 0 && (
                            <button className="apm-btn-danger" onClick={handleBulkDelete}>
                                <FaTrash /> Delete Selected ({selectedIds.length})
                            </button>
                        )}
                    </div>
                    <div className="apm-table-wrapper">
                        <table className="apm-table">
                            <thead>
                                <tr>
                                    <th style={{width: '40px'}}>
                                        <input type="checkbox" onChange={handleSelectAll} checked={selectedIds.length > 0 && selectedIds.length === filteredLessons.length} />
                                    </th>
                                    <th>ID</th>
                                    <th>Project Name</th>
                                    <th>Type</th>
                                    <th>Level</th>
                                    <th>Order</th>
                                    <th style={{textAlign: 'right'}}>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredLessons.map(l => (
                                    <tr key={l.id} className={selectedIds.includes(l.id) ? 'selected' : ''}>
                                        <td>
                                            <input type="checkbox" checked={selectedIds.includes(l.id)} onChange={() => handleToggleSelect(l.id)} />
                                        </td>
                                        <td className="apm-id">{l.id}</td>
                                        <td>
                                            <div className="apm-project-title">{l.title}</div>
                                            <div className="apm-project-obj">{l.objective}</div>
                                        </td>
                                        <td>
                                            {l.is_prompt_project ? 
                                                <span className="apm-badge-prompt"><FaMagic /> Prompt</span> : 
                                                <span className="apm-badge-regular">Standard</span>
                                            }
                                        </td>
                                        <td><span className="apm-level-pill">Lvl {l.class_level}</span></td>
                                        <td>{l.order_index}</td>
                                        <td style={{textAlign: 'right'}}>
                                            <button className="apm-icon-btn edit" title="Edit" onClick={() => handleEdit(l)}><FaEdit /></button>
                                            <button className="apm-icon-btn delete" title="Delete" onClick={() => handleDelete(l.id)}><FaTrash /></button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {activeTab === 'bulk' && (
                <div className="apm-card apm-bulk-card">
                    <div className="apm-bulk-header">
                        <FaUpload className="apm-bulk-icon" />
                        <h2>Bulk Project Injection</h2>
                        <p>Upload a CSV file or paste data to add/update projects instantly.</p>
                    </div>

                    <div className="apm-bulk-grid">
                        <div className="apm-bulk-upload-zone">
                            <input type="file" id="csvUpload" accept=".csv" onChange={handleFileUpload} hidden />
                            <label htmlFor="csvUpload" className="apm-upload-label">
                                <FaUpload /> Choose CSV File
                            </label>
                            <div className="apm-divider">OR PASTE DATA</div>
                            <textarea 
                                className="apm-paste-area" 
                                placeholder="Paste your CSV data here..." 
                                value={csvText}
                                onChange={e => setCsvText(e.target.value)}
                            />
                            <button className="apm-btn-primary" style={{width: '100%'}} onClick={handlePasteSubmit} disabled={uploading}>
                                {uploading ? 'Synthesizing...' : 'Sync Curriculum'}
                            </button>
                        </div>

                        <div className="apm-synthesis-panel">
                            <h3>Deep Synthesis Status</h3>
                            <div className="apm-log-list">
                                {synthesisLogs.length === 0 && <p className="text-muted">Waiting for curriculum...</p>}
                                {synthesisLogs.map((log, idx) => (
                                    <div key={idx} className={`apm-log-item ${log.status}`}>
                                        <span className="log-id">{log.id}</span>
                                        <span className="log-status">{log.status === 'processing' ? '⚙️' : '✅'}</span>
                                        <span className="log-details">{log.details}</span>
                                    </div>
                                ))}
                            </div>
                            {uploading && (
                                <div className="apm-progress-container">
                                    <div className="apm-progress-bar" style={{ width: `${uploadProgress}%` }}></div>
                                    <div className="apm-progress-text">{uploadProgress}% Complete</div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {activeTab === 'edit' && (
                <div className="apm-form-container-no-card" style={{ padding: '20px' }}>
                    <div className="apm-form-header" style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '20px' }}>
                        <h2><FaEdit /> {form.id ? 'Edit Project Definition' : 'Create New Project'}</h2>
                        <button type="button" className="btn btn-secondary" onClick={() => setActiveTab('list')}>Close Editor</button>
                    </div>

                    {/* AI Prompt Auto-Generator */}
                    <div className="row g-4 mb-4">
                        <div className="col-12">
                            <div className="p-4" style={{ background: '#EEF2FF', borderRadius: '16px', border: '2px solid #C7D2FE' }}>
                                <h4 className="text-primary fw-bold mb-3"><FaMagic /> AI Auto-Generate Project</h4>
                                <div className="d-flex gap-3">
                                    <textarea 
                                        className="form-control shadow-sm" 
                                        rows="2" 
                                        placeholder="E.g., Make a level 2 project about a cat jumping over a ball to teach loops..."
                                        value={aiPrompt}
                                        onChange={(e) => setAiPrompt(e.target.value)}
                                        style={{ resize: 'none' }}
                                    />
                                    <button 
                                        className="btn btn-primary d-flex align-items-center justify-content-center" 
                                        onClick={handleMagicSynthesis} 
                                        disabled={isGenerating}
                                        style={{ minWidth: '150px', background: 'linear-gradient(135deg, #6366F1, #8B5CF6)', border: 'none' }}
                                    >
                                        {isGenerating ? <FaCogs className="apm-spin" /> : 'Generate'}
                                    </button>
                                </div>
                                <small className="text-muted mt-2 d-block">Powered by AI Agent. Write a prompt and it will auto-fill the entire form below.</small>
                            </div>
                        </div>
                    </div>

                    <form onSubmit={handleSave} className="row g-4">
                        {/* Core Identity Section */}
                        <div className="col-lg-6 d-flex flex-column gap-3">
                            <h3 className="section-title"><FaBookOpen /> Core Identity</h3>
                            
                            <div>
                                <label className="form-label fw-bold">Unique ID (e.g., L1P1)</label>
                                <input type="text" className="form-control form-control-lg shadow-sm" value={form.id} onChange={e => setForm({...form, id: e.target.value})} disabled={!!editingProject} required />
                            </div>
                            
                            <div>
                                <label className="form-label fw-bold">Project Name</label>
                                <input type="text" className="form-control form-control-lg shadow-sm" value={form.title} onChange={e => setForm({...form, title: e.target.value})} required />
                            </div>
                            
                            <div className="row">
                                <div className="col-6">
                                    <label className="form-label fw-bold">Level</label>
                                    <input type="number" className="form-control form-control-lg shadow-sm" value={form.class_level} onChange={e => setForm({...form, class_level: parseInt(e.target.value)})} />
                                </div>
                                <div className="col-6">
                                    <label className="form-label fw-bold">Sequence #</label>
                                    <input type="number" className="form-control form-control-lg shadow-sm" value={form.order_index} onChange={e => setForm({...form, order_index: parseInt(e.target.value)})} />
                                </div>
                            </div>
                            
                            <div>
                                <label className="form-label fw-bold">Student Objective</label>
                                <textarea className="form-control form-control-lg shadow-sm" rows="3" value={form.objective} onChange={e => setForm({...form, objective: e.target.value})} />
                            </div>
                        </div>

                        {/* Agent Training Section */}
                        <div className="col-lg-6 d-flex flex-column gap-3" style={{ background: '#F5F7FF', padding: '30px', borderRadius: '24px', border: '2px dashed #C7D2FE' }}>
                            <div className="d-flex justify-content-between align-items-center mb-2">
                                <h3 className="section-title mb-0 text-primary border-0"><FaRobot /> Agent Training Matrix</h3>
                            </div>
                            
                            <div>
                                <label className="form-label fw-bold text-muted">Solving Intelligence (Plain Text)</label>
                                <textarea 
                                    className="form-control shadow-sm"
                                    rows="3"
                                    value={form.agent_solve_description} 
                                    onChange={e => setForm({...form, agent_solve_description: e.target.value})} 
                                    placeholder="Describe how to solve. The agent will auto-generate XML."
                                />
                            </div>
                            
                            <div>
                                <label className="form-label fw-bold text-muted">Guide Agent Logic (Step by Step)</label>
                                <textarea 
                                    className="form-control shadow-sm"
                                    rows="3"
                                    value={form.agent_tutorial_description} 
                                    onChange={e => setForm({...form, agent_tutorial_description: e.target.value})} 
                                    placeholder="1. Pick block... 2. Add flag..."
                                />
                            </div>
                            
                            <div className="row mt-2">
                                <div className="col-6">
                                    <label className="form-label fw-bold text-muted">Agent Tip</label>
                                    <input type="text" className="form-control shadow-sm" value={form.agent_solve_tip} onChange={e => setForm({...form, agent_solve_tip: e.target.value})} />
                                </div>
                                <div className="col-6">
                                    <label className="form-label fw-bold text-muted">Success Message</label>
                                    <input type="text" className="form-control shadow-sm" value={form.agent_solve_message} onChange={e => setForm({...form, agent_solve_message: e.target.value})} />
                                </div>
                            </div>
                        </div>

                        <div className="col-12 mt-4">
                            <button type="submit" className="btn btn-primary btn-lg px-5 shadow" disabled={uploading} style={{ background: 'linear-gradient(135deg, #6366F1, #8B5CF6)', border: 'none' }}>
                                {uploading ? <><FaCogs className="apm-spin" /> Training Agent...</> : 'Save & Deploy Project'}
                            </button>
                        </div>
                    </form>
                </div>
            )}

            <style>{`
                .apm-container { padding: 40px; font-family: 'Fredoka', sans-serif; background: #F8FAFC; min-height: 100vh; animation: fadeIn 0.4s ease-out; }
                @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
                
                .apm-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 40px; }
                .apm-title { font-weight: 900; font-size: 2.2rem; color: #1E293B; margin: 0; letter-spacing: -1px; }
                .apm-subtitle { color: #64748B; font-size: 1.1rem; margin: 5px 0 0; }
                
                .apm-actions { display: flex; gap: 15px; }
                .apm-tab-btn { padding: 12px 24px; border-radius: 16px; border: 2px solid transparent; background: #fff; color: #64748B; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 10px; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
                .apm-tab-btn.active { background: #EEF2FF; border-color: #6366F1; color: #6366F1; transform: translateY(-2px); box-shadow: 0 8px 20px rgba(99,102,241,0.15); }
                
                .apm-btn-primary { padding: 12px 28px; border-radius: 16px; border: none; background: linear-gradient(135deg, #6366F1, #8B5CF6); color: #fff; font-weight: 800; cursor: pointer; transition: all 0.3s; box-shadow: 0 6px 18px rgba(99,102,241,0.3); }
                .apm-btn-primary:hover { transform: translateY(-3px); box-shadow: 0 10px 25px rgba(99,102,241,0.4); }
                .apm-btn-primary:disabled { opacity: 0.7; transform: none; }

                .apm-card { background: #fff; border-radius: 32px; border: 1px solid #E2E8F0; box-shadow: 0 10px 40px rgba(0,0,0,0.04); padding: 40px; }
                
                .apm-table-tools { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; gap: 20px; }
                .apm-search-wrapper { flex: 1; max-width: 400px; }
                .apm-search { width: 100%; padding: 14px 20px; border-radius: 16px; border: 2px solid #F1F5F9; background: #F8FAFC; font-weight: 600; transition: all 0.2s; outline: none; }
                .apm-search:focus { border-color: #6366F1; background: #fff; box-shadow: 0 0 0 4px rgba(99,102,241,0.1); }

                .apm-table { width: 100%; border-collapse: separate; border-spacing: 0 12px; }
                .apm-table th { padding: 15px 25px; color: #94A3B8; font-weight: 800; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1.5px; }
                .apm-table tr { transition: all 0.2s; }
                .apm-table tr:hover { transform: scale(1.005); }
                .apm-table tr.selected { background: #F5F7FF; }
                .apm-table td { padding: 20px 25px; background: #fff; border-top: 1px solid #F1F5F9; border-bottom: 1px solid #F1F5F9; vertical-align: middle; }
                .apm-table td:first-child { border-left: 1px solid #F1F5F9; border-radius: 20px 0 0 20px; }
                .apm-table td:last-child { border-right: 1px solid #F1F5F9; border-radius: 0 20px 20px 0; }
                
                .apm-id { font-family: 'JetBrains Mono', monospace; color: #6366F1; font-weight: 800; }
                .apm-project-title { font-weight: 800; color: #1E293B; font-size: 1.1rem; margin-bottom: 4px; }
                .apm-project-obj { font-size: 0.85rem; color: #94A3B8; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }

                .apm-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; }
                .apm-form-column { display: flex; flexDirection: column; gap: 20px; }
                .section-title { font-size: 1.1rem; font-weight: 800; color: #1E293B; margin: 0 0 10px; display: flex; align-items: center; gap: 10px; border-bottom: 2px solid #F1F5F9; padding-bottom: 12px; }
                .agent-training { background: #F5F7FF; padding: 30px; border-radius: 24px; border: 2px dashed #C7D2FE; }
                .agent-training .section-title { color: #6366F1; border-color: #C7D2FE; }
                
                .apm-field { display: flex; flexDirection: column; gap: 8px; }
                .apm-field label { font-weight: 800; color: #64748B; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px; }
                .apm-field input, .apm-field select, .apm-field textarea { padding: 14px 18px; border-radius: 16px; border: 2px solid #E2E8F0; background: #fff; font-family: inherit; font-weight: 600; outline: none; transition: all 0.2s; }
                .apm-field textarea { height: 120px; line-height: 1.5; resize: none; }
                .agent-text { background: #fff !important; border-color: #C7D2FE !important; font-size: 0.9rem; }
                .apm-form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
                .apm-form-footer { grid-column: span 2; margin-top: 20px; }

                .apm-btn-close { background: #F1F5F9; border: none; padding: 8px 16px; border-radius: 10px; font-weight: 800; color: #64748B; cursor: pointer; }
                .apm-icon-btn { width: 40px; height: 40px; border-radius: 12px; border: none; margin-left: 10px; cursor: pointer; font-size: 1.1rem; transition: all 0.2s; }
                .apm-icon-btn.edit { background: #EEF2FF; color: #6366F1; }
                .apm-icon-btn.delete { background: #FEF2F2; color: #EF4444; }

                .apm-bulk-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; margin-top: 30px; }
                .apm-synthesis-panel { background: #0F172A; border-radius: 24px; padding: 30px; color: #fff; display: flex; flexDirection: column; min-height: 400px; }
                .apm-log-list { flex: 1; overflow-y: auto; max-height: 350px; margin-bottom: 20px; }
                .apm-log-item { padding: 12px 0; border-bottom: 1px solid #1E293B; display: flex; align-items: center; gap: 15px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; }
                .apm-log-item.complete { color: #4ADE80; }
                
                .apm-alert { padding: 16px 20px; border-radius: 16px; margin-bottom: 24px; display: flex; align-items: center; gap: 12px; font-weight: 700; position: relative; }
                .apm-alert.success { background: #F0FDF4; color: #16A34A; border: 1px solid #BBF7D0; }
                .apm-alert.error { background: #FEF2F2; color: #EF4444; border: 1px solid #FECACA; }
                .apm-alert-close { position: absolute; right: 15px; background: none; border: none; color: inherit; font-size: 1.2rem; cursor: pointer; }

                .apm-progress-container { width: 100%; background: #1E293B; height: 12px; border-radius: 10px; overflow: hidden; position: relative; }
                .apm-progress-bar { height: 100%; background: linear-gradient(90deg, #6366F1, #8B5CF6); transition: width 0.3s ease; }
                .apm-progress-text { margin-top: 8px; font-size: 0.75rem; font-weight: 800; color: #6366F1; }

                .apm-badge-prompt { background: #F0FDF4; color: #16A34A; padding: 4px 10px; border-radius: 8px; font-size: 0.75rem; font-weight: 800; display: inline-flex; align-items: center; gap: 5px; }
                .apm-badge-regular { background: #F1F5F9; color: #64748B; padding: 4px 10px; border-radius: 8px; font-size: 0.75rem; font-weight: 800; }
                .apm-level-pill { background: #EEF2FF; color: #6366F1; padding: 4px 10px; border-radius: 8px; font-size: 0.75rem; font-weight: 800; }

                .apm-divider { margin: 20px 0; font-weight: 800; color: #334155; font-size: 0.8rem; }
                .apm-upload-label { display: block; padding: 16px; background: #6366F1; color: #fff; border-radius: 16px; font-weight: 800; cursor: pointer; text-align: center; }
                .apm-paste-area { width: 100%; height: 200px; border-radius: 16px; border: 1.5px solid #1E293B; padding: 15px; font-family: monospace; font-size: 0.85rem; margin-bottom: 15px; resize: none; background: #0F172A; color: #fff; }

                .apm-btn-magic { padding: 8px 16px; border-radius: 12px; border: none; background: #0F172A; color: #4ADE80; font-weight: 800; cursor: pointer; display: flex; align-items: center; gap: 8px; transition: all 0.2s; font-size: 0.8rem; }
                .apm-btn-magic:hover { background: #1E293B; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(74,222,128,0.2); }
                .apm-btn-magic:disabled { opacity: 0.5; cursor: not-allowed; }

                .apm-spin { animation: spin 1s linear infinite; }
                @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
            `}</style>
        </div>
    );
};

export default AdminProjectManager;
