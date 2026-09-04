import React, { useState } from 'react';
import { playSound } from './soundEngine';
import { BACKDROPS } from './constants';
import tutorBot from '../../assets/tutor.png';

// ─── Smart keyword extractor from milestone label ───────────────────────────
function parseMilestone(raw, index) {
    if (typeof raw !== 'string') {
        return { id: raw.id || 'ms_' + index, keyword: raw.keyword || '', action: raw.action || 'say:Done!', label: raw.label || raw.keyword || '' };
    }

    const lower = raw.toLowerCase();
    let action = 'say:Done!';
    // Extract meaningful keyword(s) from the label text
    let keyword = raw; // fallback: use entire label as keyword

    // Background-related
    if (lower.includes('space') || lower.includes('galaxy') || lower.includes('star')) {
        action = 'bg:space'; keyword = 'space';
    } else if (lower.includes('jungle') || lower.includes('forest') || lower.includes('tree')) {
        action = 'bg:jungle'; keyword = 'jungle';
    } else if (lower.includes('ocean') || lower.includes('sea') || lower.includes('underwater') || lower.includes('water')) {
        action = 'bg:ocean'; keyword = 'ocean';
    } else if (lower.includes('castle') || lower.includes('kingdom')) {
        action = 'bg:castle'; keyword = 'castle';
    } else if (lower.includes('city') || lower.includes('town')) {
        action = 'bg:city'; keyword = 'city';
    } else if (lower.includes('desert') || lower.includes('sand')) {
        action = 'bg:desert'; keyword = 'desert';
    } else if (lower.includes('background') || lower.includes('scene') || lower.includes('world')) {
        action = 'bg:sky'; keyword = 'background';
    }
    // Speech / say
    else if (lower.includes('hello') || lower.includes('hi ') || lower.includes('greet') || lower.includes('introduce') || lower.includes('says hello') || lower.includes('speak') || lower.includes('say')) {
        action = 'say:Hello! I am Kido, your AI friend!'; keyword = 'hello';
    }
    // Robot / character speaks
    else if (lower.includes('robot')) {
        action = 'say:Beep boop! I am a robot!'; keyword = 'robot';
    } else if (lower.includes('dinosaur') || lower.includes('dino')) {
        action = 'say:RAWR! I love eating leaves!'; keyword = 'dinosaur';
    }
    // Movement
    else if (lower.includes('move') || lower.includes('walk') || lower.includes('run') || lower.includes('go')) {
        action = 'move:80'; keyword = 'move';
    } else if (lower.includes('glide') || lower.includes('slide') || lower.includes('float')) {
        action = 'move:glide'; keyword = 'glide';
    }
    // Color / appearance
    else if (lower.includes('color') || lower.includes('colour') || lower.includes('rainbow') || lower.includes('bright')) {
        action = 'effect:color'; keyword = 'color';
    }
    // Sound / music
    else if (lower.includes('sound') || lower.includes('music') || lower.includes('meow') || lower.includes('bark') || lower.includes('sing')) {
        action = 'sound:pop'; keyword = 'sound';
    }
    // Story / text keywords for prompt lessons
    else if (lower.includes('library') || lower.includes('book')) {
        action = 'say:I love the library!'; keyword = 'library';
    } else if (lower.includes('portal') || lower.includes('door') || lower.includes('gate')) {
        action = 'say:Found a secret portal!'; keyword = 'portal';
    } else if (lower.includes('crystal') || lower.includes('gem') || lower.includes('collect')) {
        action = 'effect:color'; keyword = 'crystal';
    } else if (lower.includes('monster') || lower.includes('enemy') || lower.includes('defeat') || lower.includes('shadow')) {
        action = 'effect:color'; keyword = 'monster';
    } else if (lower.includes('cat') || lower.includes('magical cat')) {
        action = 'say:I am a magical cat!'; keyword = 'cat';
    } else if (lower.includes('wing') || lower.includes('fly') || lower.includes('cloud')) {
        action = 'move:glide'; keyword = 'wing';
    } else if (lower.includes('food') || lower.includes('eat') || lower.includes('pizza') || lower.includes('cake')) {
        action = 'say:Yum! I love food!'; keyword = 'food';
    } else if (lower.includes('storm') || lower.includes('save') || lower.includes('kido world')) {
        action = 'effect:color'; keyword = 'storm';
    } else if (lower.includes('character') || lower.includes('hero') || lower.includes('all')) {
        action = 'say:All heroes together!'; keyword = 'character';
    }

    return { id: 'ms_' + index, keyword, action, label: raw };
}

// ─── Multi-keyword fuzzy match ────────────────────────────────────────────────
function inputMatchesMilestone(inputLower, milestone) {
    const kw = milestone.keyword.toLowerCase();
    const label = milestone.label.toLowerCase();

    // Direct keyword match
    if (kw && inputLower.includes(kw)) return true;

    // Check individual meaningful words from the label (length > 3)
    const labelWords = label.split(/\s+/).filter(w => w.length > 3);
    for (const word of labelWords) {
        if (inputLower.includes(word)) return true;
    }

    return false;
}

const PromptWorkspace = ({
    lesson,
    sp,
    switchBackdrop,
    projectBackdropsRef,
    addLog,
    onComplete,
    _force
}) => {
    const [input, setInput] = useState('');
    const [completedMilestones, setCompletedMilestones] = useState([]);
    const [response, setResponse] = useState("Hi! I'm Kido. Type your magic command and I'll make it happen!");
    const [isAllDone, setIsAllDone] = useState(false);

    const milestones = (lesson?.prompt_milestones || []).map(parseMilestone);

    const executeAction = (actionStr) => {
        if (!actionStr) return;
        const colonIdx = actionStr.indexOf(':');
        const cmd = colonIdx === -1 ? actionStr : actionStr.slice(0, colonIdx);
        const value = colonIdx === -1 ? '' : actionStr.slice(colonIdx + 1);

        try {
            switch (cmd) {
                case 'move':
                    if (sp?.current) {
                        if (value === 'glide') {
                            const targetX = Math.min(sp.current.x + 120, 460);
                            const steps = 20;
                            let s = 0;
                            const iv = setInterval(() => {
                                if (s++ >= steps) { clearInterval(iv); return; }
                                sp.current.x += (targetX - sp.current.x) * 0.15;
                                _force(x => x + 1);
                            }, 40);
                        } else {
                            sp.current.x = Math.min(sp.current.x + (parseInt(value) || 80), 460);
                            _force(x => x + 1);
                        }
                    }
                    break;
                case 'say':
                    if (sp?.current) {
                        sp.current.speech = value || 'Hello!';
                        sp.current.bubbleType = 'say';
                        _force(x => x + 1);
                        setTimeout(() => { if (sp?.current) { sp.current.speech = null; _force(x => x + 1); } }, 3500);
                    }
                    break;
                case 'bg':
                    const idx = BACKDROPS.findIndex(b => b.name.toLowerCase().includes(value.toLowerCase()));
                    if (idx !== -1) {
                        switchBackdrop(idx);
                    } else if (projectBackdropsRef?.current?.length > 0) {
                        const pb = projectBackdropsRef.current.find(b => b.name?.toLowerCase().includes(value.toLowerCase()));
                        if (pb) switchBackdrop(pb.id);
                    }
                    break;
                case 'effect':
                    if (sp?.current) {
                        sp.current.colorHue = ((sp.current.colorHue || 0) + 40) % 360;
                        _force(x => x + 1);
                    }
                    break;
                case 'sound':
                    playSound(value || 'pop');
                    break;
                default:
                    break;
            }
        } catch (e) { console.error('Action error', e); }
    };

    const handleRunPrompt = () => {
        if (!input.trim() || isAllDone) return;
        const inputLower = input.toLowerCase();
        const newCompleted = [...completedMilestones];
        let matched = false;

        milestones.forEach(m => {
            if (!newCompleted.includes(m.id) && inputMatchesMilestone(inputLower, m)) {
                executeAction(m.action);
                newCompleted.push(m.id);
                matched = true;
            }
        });

        setCompletedMilestones(newCompleted);
        setInput('');

        if (matched) {
            playSound('collect');
            addLog('AI: prompt matched!');

            if (milestones.length > 0 && newCompleted.length >= milestones.length) {
                setIsAllDone(true);
                setResponse('AMAZING! You completed all milestones! You are a Prompt Master!');
                playSound('success');
                setTimeout(() => onComplete && onComplete(), 1500);
            } else {
                const remaining = milestones.length - newCompleted.length;
                setResponse(`Great job! ${remaining} milestone${remaining !== 1 ? 's' : ''} left. Keep going!`);
            }
        } else if (milestones.length === 0) {
            // Free-form lesson — any input counts
            setResponse("Awesome creative thinking! Your imagination is the limit! Keep exploring!");
            playSound('collect');
            addLog('AI: free-form prompt submitted');
            if (!isAllDone) {
                setIsAllDone(true);
                setTimeout(() => onComplete && onComplete(), 2000);
            }
        } else {
            setResponse("Hmm, I need more detail. Try mentioning keywords from the milestone list below!");
            addLog('AI: no match for "' + input + '"');
        }
    };

    const progressPct = milestones.length > 0 ? Math.round((completedMilestones.length / milestones.length) * 100) : (isAllDone ? 100 : 0);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'linear-gradient(180deg, #EEF2FF 0%, #F0FDF4 100%)', overflowY: 'auto' }}>

            {/* Header */}
            <div style={{ padding: '16px 20px', background: '#6366F1', display: 'flex', alignItems: 'center', gap: 12 }}>
                <img src={tutorBot} style={{ width: 50, height: 50, borderRadius: '50%', border: '3px solid #fff' }} alt="kido" />
                <div>
                    <div style={{ color: '#fff', fontWeight: 900, fontSize: 14 }}>Kido AI Studio</div>
                    <div style={{ color: 'rgba(255,255,255,0.8)', fontSize: 11, fontWeight: 600 }}>{lesson?.title || 'Prompt Challenge'}</div>
                </div>
                {milestones.length > 0 && (
                    <div style={{ marginLeft: 'auto', background: 'rgba(255,255,255,0.2)', borderRadius: 20, padding: '4px 14px', color: '#fff', fontWeight: 900, fontSize: 13 }}>
                        {completedMilestones.length}/{milestones.length}
                    </div>
                )}
            </div>

            {/* Progress bar */}
            {milestones.length > 0 && (
                <div style={{ height: 6, background: 'rgba(99,102,241,0.15)' }}>
                    <div style={{ height: '100%', width: progressPct + '%', background: 'linear-gradient(90deg, #6366F1, #22C55E)', transition: 'width 0.6s ease', borderRadius: '0 4px 4px 0' }} />
                </div>
            )}

            <div style={{ flex: 1, padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 14 }}>

                {/* Kido Response Bubble */}
                <div style={{ background: '#fff', borderRadius: 18, padding: '14px 18px', border: '2px solid #6366F1', boxShadow: '0 4px 16px rgba(99,102,241,0.12)' }}>
                    <div style={{ fontSize: 11, fontWeight: 900, color: '#6366F1', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>Kido says</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: '#1E293B', lineHeight: 1.5 }}>{response}</div>
                </div>

                {/* Objective */}
                {lesson?.objective && (
                    <div style={{ background: '#FFFBEB', borderRadius: 14, padding: '10px 16px', border: '2px solid #FDE68A' }}>
                        <div style={{ fontSize: 11, fontWeight: 900, color: '#92400E', textTransform: 'uppercase', marginBottom: 4 }}>Mission Objective</div>
                        <div style={{ fontSize: 13, color: '#78350F', fontWeight: 700 }}>{lesson.objective}</div>
                    </div>
                )}

                {/* Perfect Prompt Hint */}
                {lesson?.perfect_prompt && !isAllDone && (
                    <details style={{ background: '#F0FDF4', borderRadius: 14, border: '2px solid #86EFAC', padding: '10px 16px' }}>
                        <summary style={{ fontSize: 12, fontWeight: 900, color: '#166534', cursor: 'pointer' }}>Hint: See a perfect prompt</summary>
                        <div style={{ fontSize: 12, color: '#14532D', marginTop: 8, fontStyle: 'italic', lineHeight: 1.5 }}>"{lesson.perfect_prompt}"</div>
                    </details>
                )}

                {/* Milestones */}
                {milestones.length > 0 && (
                    <div style={{ background: '#fff', borderRadius: 16, border: '2px solid #E2E8F0', overflow: 'hidden' }}>
                        <div style={{ padding: '10px 16px', background: '#F8FAFC', borderBottom: '1px solid #E2E8F0', fontSize: 11, fontWeight: 900, color: '#64748B', textTransform: 'uppercase', letterSpacing: 1 }}>
                            Milestones to Complete
                        </div>
                        {milestones.map(m => {
                            const done = completedMilestones.includes(m.id);
                            return (
                                <div key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', borderBottom: '1px solid #F1F5F9', background: done ? '#F0FDF4' : '#fff', transition: 'background 0.3s' }}>
                                    <div style={{ width: 22, height: 22, borderRadius: '50%', flexShrink: 0, background: done ? '#22C55E' : '#E2E8F0', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, color: '#fff', fontWeight: 900, transition: 'background 0.3s' }}>
                                        {done ? '✓' : ''}
                                    </div>
                                    <span style={{ fontSize: 13, fontWeight: 700, color: done ? '#166534' : '#475569', textDecoration: done ? 'line-through' : 'none' }}>
                                        {m.label}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                )}

                {/* Input */}
                <div style={{ background: '#fff', borderRadius: 18, border: '2px solid #CBD5E1', padding: 12, boxShadow: '0 2px 10px rgba(0,0,0,0.06)', marginTop: 'auto' }}>
                    <div style={{ fontSize: 11, fontWeight: 800, color: '#94A3B8', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1 }}>
                        {isAllDone ? 'Challenge Complete!' : 'Your Prompt Command'}
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                        <input
                            value={input}
                            onChange={e => setInput(e.target.value)}
                            onKeyDown={e => e.key === 'Enter' && handleRunPrompt()}
                            disabled={isAllDone}
                            placeholder={isAllDone ? 'All done! Amazing work!' : 'Tell Kido what to do...'}
                            style={{ flex: 1, padding: '10px 16px', borderRadius: 12, border: '2px solid #E2E8F0', fontSize: 14, fontWeight: 600, outline: 'none', background: isAllDone ? '#F0FDF4' : '#fff', transition: 'border 0.2s' }}
                        />
                        <button
                            onClick={handleRunPrompt}
                            disabled={isAllDone || !input.trim()}
                            style={{ padding: '0 20px', background: isAllDone ? '#22C55E' : '#6366F1', color: '#fff', borderRadius: 12, border: 'none', fontWeight: 900, fontSize: 14, cursor: isAllDone ? 'default' : 'pointer', opacity: (!input.trim() && !isAllDone) ? 0.5 : 1, transition: 'all 0.2s', flexShrink: 0 }}
                        >
                            {isAllDone ? 'Done!' : 'SEND'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default PromptWorkspace;
