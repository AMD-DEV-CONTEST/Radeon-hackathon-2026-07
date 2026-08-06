import React, { useState } from 'react';
import { FaTrash, FaFlagCheckered, FaKey, FaTimes, FaCircleNotch } from 'react-icons/fa';
import hero1 from '../../assets/hero1.png';
import { S } from './styles';
import { supabase } from '../../utils/supabaseClient';

export function SidebarPanel({
    sidebarOpen, LESSON, solveProject, tutorState, tutorialStep, startTutorial, log, setLog, levelStats, isPromptProject
}) {
    const isMobile = window.innerWidth < 900;
    const [showKeyModal, setShowKeyModal] = useState(false);
    const [parentKeyInput, setParentKeyInput] = useState('');
    const [coMentorUses, setCoMentorUses] = useState(0);
    const [coMentorUnlocked, setCoMentorUnlocked] = useState(false);
    const [verifyingKey, setVerifyingKey] = useState(false);
    const [keyError, setKeyError] = useState('');

    const handleCoMentorClick = () => {
        if (coMentorUnlocked || coMentorUses < 1) {
            setCoMentorUses(prev => prev + 1);
            solveProject(LESSON);
        } else {
            setShowKeyModal(true);
            setKeyError('');
        }
    };

    const verifyParentKey = async () => {
        if (!parentKeyInput.trim()) {
            setKeyError('Please enter a key.');
            return;
        }
        setVerifyingKey(true);
        setKeyError('');
        try {
            const childId = localStorage.getItem('kido_child_id');
            if (childId) {
                const { data: childData } = await supabase.from('children').select('parent_id').eq('id', childId).single();
                if (childData?.parent_id) {
                    const { data: parentData } = await supabase.from('parent_profiles').select('co_mentor_key').eq('id', childData.parent_id).single();
                    if (parentData?.co_mentor_key === parentKeyInput.trim()) {
                        setCoMentorUnlocked(true);
                        setShowKeyModal(false);
                        setParentKeyInput('');
                        solveProject(LESSON);
                        return;
                    }
                }
                setKeyError('Invalid Parent Key. Ask your parent for the key!');
            } else {
                // Not a child profile, just allow it
                setCoMentorUnlocked(true);
                setShowKeyModal(false);
                solveProject(LESSON);
            }
        } catch (err) {
            console.error("Key verification error", err);
            setKeyError('Error verifying key.');
        } finally {
            setVerifyingKey(false);
        }
    };

    return (
        <div style={{
            ...S.side,
            width: sidebarOpen ? 260 : 0,
            opacity: sidebarOpen ? 1 : 0,
            transition: 'all 0.3s ease-in-out',
            overflow: 'hidden',
            position: isMobile ? 'absolute' : 'relative',
            zIndex: 50,
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
        }}>
            {/* Blurry Sidebar Background */}
            <div style={{
                position: 'absolute',
                inset: -20,
                backgroundImage: `url(${hero1})`,
                backgroundSize: 'cover',
                backgroundPosition: 'center',
                filter: 'blur(12px) brightness(0.6)',
                zIndex: 0
            }} />

            {/* Static content container on top of background */}
            <div style={{
                position: 'relative',
                zIndex: 1,
                display: 'flex',
                flexDirection: 'column',
                flex: 1,
                minWidth: 260,
                minHeight: 0,       /* ← lets flex children shrink */
                overflow: 'hidden',
            }}>
                {/* Scrollable area — everything EXCEPT the button */}
                <div style={{
                    flex: 1,
                    overflowY: 'auto',
                    padding: 15,
                    paddingBottom: isPromptProject ? 15 : 0,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10
                }}>
                    {/* Level Progress Stats */}
                    <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                        <div style={{ flex: 1, background: 'rgba(255,255,255,0.15)', backdropFilter: 'blur(10px)', borderRadius: 12, padding: '8px 4px', border: '1.5px solid rgba(255,255,255,0.2)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                            <span style={{ fontSize: 10, color: '#FFD700', fontWeight: 900, textTransform: 'uppercase' }}>Stars</span>
                            <span style={{ fontSize: 14, color: '#fff', fontWeight: 950 }}>{levelStats?.obtainedStars || 0}/{levelStats?.totalStars || 0}</span>
                        </div>
                        <div style={{ flex: 1, background: 'rgba(255,255,255,0.15)', backdropFilter: 'blur(10px)', borderRadius: 12, padding: '8px 4px', border: '1.5px solid rgba(255,255,255,0.2)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                            <span style={{ fontSize: 10, color: '#4ECDC4', fontWeight: 900, textTransform: 'uppercase' }}>Missions</span>
                            <span style={{ fontSize: 14, color: '#fff', fontWeight: 950 }}>{levelStats?.finishedMissions || 0}/{levelStats?.totalMissions || 0}</span>
                        </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                        <div style={{ width: 32, height: 32, background: '#D32F2F', border: '2px solid #fff', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 900, color: '#fff', boxShadow: '0 4px 10px rgba(0,0,0,0.2)' }}>Q</div>
                        <h3 style={{ color: '#fff', fontWeight: 900, fontSize: 16, margin: 0, textShadow: '0 2px 10px rgba(0,0,0,0.4)' }}>Mission</h3>
                    </div>

                    <div style={{ background: 'rgba(255, 255, 255, 0.9)', backdropFilter: 'blur(10px)', border: '3px solid #8BC34A', borderRadius: 12, padding: 12, boxShadow: '0 8px 32px rgba(0,0,0,0.1)' }}>
                        <h4 style={{ color: '#1B5E20', fontSize: 13, margin: '0 0 6px', fontWeight: 900 }}>{LESSON.title}</h4>
                        <p style={{ color: '#2E7D32', fontSize: 11, lineHeight: 1.5, margin: 0, fontWeight: 900 }}>{LESSON.objective}</p>
                    </div>

                    <div style={{ color: '#FFD700', fontSize: 12, fontWeight: 950, marginTop: 15, textTransform: 'uppercase', letterSpacing: 2, textShadow: '0 2px 4px rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', gap: 8 }}>
                        <FaFlagCheckered size={14} /> {isPromptProject ? 'AI Prompt Challenge' : 'Journey Goals'}
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 10 }}>
                        {(LESSON.steps || []).map((step, idx) => (
                            <div key={step.id || idx} style={{
                                borderRadius: 16, padding: '12px 14px',
                                background: 'rgba(255, 255, 255, 0.98)',
                                border: '2px solid rgba(255,255,255,0.8)',
                                boxShadow: '0 10px 20px rgba(0,0,0,0.1), inset 0 0 10px rgba(76, 175, 80, 0.05)',
                                display: 'flex', flexDirection: 'column', gap: 4,
                                position: 'relative', overflow: 'hidden'
                            }}>
                                <div style={{ position: 'absolute', top: 0, left: 0, width: 4, height: '100%', background: '#4CAF50' }} />
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <div style={{ minWidth: 22, height: 22, borderRadius: 8, background: '#4CAF50', color: '#fff', fontSize: 11, fontWeight: 950, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 8px rgba(76,175,80,0.3)' }}>{idx + 1}</div>
                                    <strong style={{ color: '#1B5E20', fontSize: 13, fontWeight: 950, letterSpacing: -0.3 }}>{step.title}</strong>
                                </div>
                                <p style={{ color: '#2E7D32', fontSize: 12, margin: 0, paddingLeft: 30, fontWeight: 800, lineHeight: 1.4 }}>{step.desc}</p>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Co-Mentor button — pinned outside the scroll area so it's always visible */}
                {!isPromptProject && (
                    <div style={{ padding: '10px 15px 15px', flexShrink: 0 }}>
                        <button
                            onClick={handleCoMentorClick}
                            disabled={tutorState.solving || tutorialStep >= 0}
                            style={{
                                width: '100%', padding: '10px', background: '#D32F2F', color: '#fff',
                                border: '3px solid #fff', borderRadius: 15, fontSize: 12, fontWeight: 900,
                                cursor: 'pointer', boxShadow: '0 4px 10px rgba(0,0,0,0.2)', transition: 'all 0.2s',
                                opacity: (tutorState.solving || tutorialStep >= 0) ? 0.5 : 1
                            }}
                        >
                            Co-Mentor
                        </button>
                    </div>
                )}
            </div>

            {/* Parent Key Modal for Co-Mentor */}
            {showKeyModal && (
                <div style={{
                    position: 'fixed', top: 0, left: 0, width: '100%', height: '100%',
                    background: 'rgba(0,0,0,0.8)', backdropFilter: 'blur(5px)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 10000
                }}>
                    <div style={{
                        background: '#fff', width: '90%', maxWidth: 350, borderRadius: 20,
                        padding: 20, textAlign: 'center', position: 'relative', boxShadow: '0 10px 40px rgba(0,0,0,0.3)'
                    }}>
                        <button 
                            onClick={() => setShowKeyModal(false)}
                            style={{ position: 'absolute', top: 10, right: 10, background: 'none', border: 'none', color: '#999', cursor: 'pointer' }}
                        >
                            <FaTimes size={18} />
                        </button>
                        <div style={{ background: '#F0F9FF', width: 50, height: 50, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 15px', color: '#0EA5E9' }}>
                            <FaKey size={24} />
                        </div>
                        <h3 style={{ color: '#1E293B', fontWeight: 900, fontSize: 18, marginBottom: 10 }}>Parent Key Required</h3>
                        <p style={{ color: '#64748B', fontSize: 13, fontWeight: 700, lineHeight: 1.4, marginBottom: 20 }}>
                            You've used your free Co-Mentor help for this session! Ask your parent for their 4-character key to unlock unlimited help.
                        </p>
                        <input
                            type="text"
                            placeholder="e.g. X9P2"
                            value={parentKeyInput}
                            onChange={(e) => setParentKeyInput(e.target.value.toUpperCase())}
                            style={{
                                width: '100%', padding: '12px 15px', border: '2px solid #E2E8F0',
                                borderRadius: 12, fontSize: 14, fontWeight: 700, textAlign: 'center',
                                outline: 'none', marginBottom: 15, fontFamily: 'monospace'
                            }}
                        />
                        {keyError && <div style={{ color: '#EF4444', fontSize: 12, fontWeight: 800, marginBottom: 15 }}>{keyError}</div>}
                        <button
                            onClick={verifyParentKey}
                            disabled={verifyingKey}
                            style={{
                                width: '100%', padding: '12px', background: '#0EA5E9', color: '#fff',
                                border: 'none', borderRadius: 12, fontSize: 14, fontWeight: 900,
                                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8
                            }}
                        >
                            {verifyingKey ? <FaCircleNotch className="fa-spin" /> : 'UNLOCK CO-MENTOR'}
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}