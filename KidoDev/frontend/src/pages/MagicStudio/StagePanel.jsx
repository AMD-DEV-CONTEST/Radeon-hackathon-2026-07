import React from 'react';
import { FaEye, FaEyeSlash } from 'react-icons/fa';
import tutorBot from '../../assets/no_bg_output/robotsprite.jpg';
import { BACKDROPS } from './constants';
import { playSound } from './soundEngine';
import { S } from './styles';
import { GuidePointer } from './GuidePointer';

export function StagePanel({
    isFullScreen, setIsFullScreen,
    canvasRef, running, asking, answer, setAnswer, submitAnswer,
    gradingResult, setGradingResult, tutorState, tutorialStep, lessonId,
    spInfo, vars, lists, panelTab, setPanelTab, bdrop, spritesRef,
    activeSpriteRef, switchSprite, deleteSprite, fileInputRef,
    handleSpriteUpload, clearCustomSprite, setLibMode, setLibCategory,
    setSearchQuery, projectSoundsRef, onMouseDown, onMouseMove, onMouseUp,
    projectBackdrops, tutorialSteps, sp, _force
}) {
    const isMobile = window.innerWidth < 900;

    const handleTouchStart = (e) => {
        if (!onMouseDown) return;
        const touch = e.touches[0];
        if (touch) {
            e.preventDefault();
            onMouseDown({
                clientX: touch.clientX,
                clientY: touch.clientY,
                preventDefault: () => {}
            });
        }
    };

    const handleTouchMove = (e) => {
        if (!onMouseMove) return;
        const touch = e.touches[0];
        if (touch) {
            e.preventDefault();
            onMouseMove({
                clientX: touch.clientX,
                clientY: touch.clientY,
                preventDefault: () => {}
            });
        }
    };

    const handleTouchEnd = (e) => {
        if (!onMouseUp) return;
        onMouseUp();
    };

    return (
        <div style={{
            ...S.stage,
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            overflow: 'hidden',
            background: '#fff',
            position: 'relative'
        }}>
            {/* Header - Shrunk for Mobile */}
            <div style={{
                padding: isMobile ? '4px 10px' : '6px 12px',
                background: '#4ECDC4',
                borderBottom: '2px solid #fff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexShrink: 0
            }}>
                <span style={{ color: '#fff', fontSize: isMobile ? 11 : 13, fontWeight: 900, textTransform: 'uppercase' }}>Stage View</span>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                    {running && <span style={{ color: '#FFE66D', fontSize: 10, fontWeight: 900 }}>LIVE</span>}
                    <button onClick={() => setIsFullScreen(!isFullScreen)} style={{ background: '#FF6B6B', border: '1.5px solid #fff', color: '#fff', borderRadius: 20, padding: '2px 10px', fontSize: 10, cursor: 'pointer', fontWeight: 800 }}>{isFullScreen ? 'Exit' : 'Full Screen'}</button>
                </div>
            </div>

            {/* Canvas Area - Precise Scaling */}
            <div className={isFullScreen ? 'stage-fullscreen-wrap' : ''} style={{
                position: 'relative',
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                background: '#000',
                zIndex: isFullScreen ? 10000 : 1,
                flex: isMobile ? '0 0 auto' : '1'
            }}>
                {isFullScreen && <button onClick={() => setIsFullScreen(false)} className="exit-fullscreen-btn">Close Full Screen</button>}
                <canvas
                    ref={canvasRef} width={480} height={360}
                    className={running ? 'stage-live ' + (isFullScreen ? 'stage-fullscreen-canvas' : '') : (isFullScreen ? 'stage-fullscreen-canvas' : '')}
                    style={{
                        display: 'block',
                        width: isFullScreen ? 'auto' : '100%',
                        height: isMobile ? '240px' : 'auto',
                        maxWidth: '100%',
                        cursor: 'grab',
                        objectFit: 'contain'
                    }}
                    onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={onMouseUp}
                    onTouchStart={handleTouchStart} onTouchMove={handleTouchMove} onTouchEnd={handleTouchEnd}
                />
            </div>

            {/* Scrollable Content Engine */}
            <div style={{ flex: 1, overflowY: 'auto', background: '#F8FAFC' }}>

                {asking && (
                    <div style={{ padding: '7px 12px', background: '#EFF6FF', borderBottom: '1px solid #BFDBFE', display: 'flex', gap: 6, alignItems: 'center' }}>
                        <span style={{ fontSize: 12, color: '#1D4ED8', fontWeight: 700, flexShrink: 0 }}>{asking}</span>
                        <input value={answer} autoFocus onChange={e => setAnswer(e.target.value)}
                            onKeyDown={e => e.key === 'Enter' && submitAnswer()}
                            style={{ flex: 1, border: '1px solid #93C5FD', borderRadius: 6, padding: '3px 8px', fontSize: 12 }}
                        />
                    </div>
                )}

                {gradingResult && (
                    <div style={{ margin: '8px', padding: '12px', borderRadius: '12px', background: 'linear-gradient(135deg, #F0F9FF, #E0F2FE)', border: '2px solid #38BDF8', display: 'flex', gap: '12px', alignItems: 'center' }}>
                        <div style={{ width: 40, height: 40, borderRadius: '50%', background: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, border: '2px solid #38BDF8', flexShrink: 0, fontWeight: 900, color: '#0369A1' }}>{gradingResult.score}</div>
                        <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 10, fontWeight: 800, color: '#0369A1' }}>KIDO SAYS:</div>
                            <div style={{ fontSize: 12, fontWeight: 700, color: '#1E293B' }}>{gradingResult.feedback}</div>
                        </div>
                        <button onClick={() => setGradingResult(null)} style={{ background: 'none', border: 'none', color: '#94A3B8', cursor: 'pointer', fontSize: 18 }}>×</button>
                    </div>
                )}

                <GuidePointer tutorialStep={tutorialStep} lessonId={lessonId} tutorialSteps={tutorialSteps} />

                {/* Sprite Manager - Hyper Compact for Mobile */}
                <div style={{ padding: '8px 12px', borderBottom: '1px solid #E2E8F0', display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                        <div style={{ flex: isMobile ? '1 0 100%' : 1, display: 'flex', alignItems: 'center', background: '#fff', border: '1px solid #CBD5E1', borderRadius: 20, overflow: 'hidden' }}>
                            <span style={{ fontSize: 9, fontWeight: 900, color: '#64748B', padding: '0 6px 0 10px' }}>SPRITE</span>
                            <input value={sp.current?.name || ''} onChange={e => { if (sp.current) sp.current.name = e.target.value; _force(x => x + 1); }}
                                style={{ flex: 1, border: 'none', fontSize: 11, fontWeight: 700, padding: '4px 0', outline: 'none' }}
                            />
                        </div>

                        <div style={{ display: 'flex', gap: 6, flex: 1 }}>
                            <div style={{ flex: 1, display: 'flex', alignItems: 'center', background: '#fff', border: '1px solid #CBD5E1', borderRadius: 20, padding: '2px 8px' }}>
                                <span style={{ fontSize: 10, fontWeight: 800, color: '#94A3B8', marginRight: 2 }}>X</span>
                                <input type="number" value={sp.current ? Math.round(sp.current.x - 240) : 0} onChange={e => { if (sp.current) { sp.current.x = Number(e.target.value) + 240; _force(x => x + 1); } }}
                                    style={{ width: '100%', border: 'none', fontSize: 11, fontWeight: 700, textAlign: 'center' }}
                                />
                            </div>
                            <div style={{ flex: 1, display: 'flex', alignItems: 'center', background: '#fff', border: '1px solid #CBD5E1', borderRadius: 20, padding: '2px 8px' }}>
                                <span style={{ fontSize: 10, fontWeight: 800, color: '#94A3B8', marginRight: 2 }}>Y</span>
                                <input type="number" value={sp.current ? Math.round(180 - sp.current.y) : 0} onChange={e => { if (sp.current) { sp.current.y = 180 - Number(e.target.value); _force(x => x + 1); } }}
                                    style={{ width: '100%', border: 'none', fontSize: 11, fontWeight: 700, textAlign: 'center' }}
                                />
                            </div>
                        </div>
                    </div>

                    <div style={{ display: 'flex', gap: 10, alignItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', gap: 4 }}>
                            <button onClick={() => { if (sp.current) { sp.current.visible = true; _force(x => x + 1); } }} style={{ width: 32, height: 28, borderRadius: 8, border: sp.current?.visible ? '2px solid #4ECDC4' : '1px solid #CBD5E1', background: sp.current?.visible ? '#4ECDC4' : '#fff', color: sp.current?.visible ? '#fff' : '#64748B' }}><FaEye size={12} /></button>
                            <button onClick={() => { if (sp.current) { sp.current.visible = false; _force(x => x + 1); } }} style={{ width: 32, height: 28, borderRadius: 8, border: !sp.current?.visible ? '2px solid #FF6B6B' : '1px solid #CBD5E1', background: !sp.current?.visible ? '#FF6B6B' : '#fff', color: !sp.current?.visible ? '#fff' : '#64748B' }}><FaEyeSlash size={12} /></button>
                        </div>
                        <div style={{ display: 'flex', gap: 6 }}>
                            <div style={{ width: 60, display: 'flex', alignItems: 'center', background: '#fff', border: '1px solid #CBD5E1', borderRadius: 20, padding: '2px 6px' }}>
                                <span style={{ fontSize: 9, fontWeight: 900, color: '#94A3B8', marginRight: 2 }}>SIZE</span>
                                <input type="number" value={sp.current ? Math.round(sp.current.size) : 100} onChange={e => { if (sp.current) { sp.current.size = Number(e.target.value); _force(x => x + 1); } }} style={{ width: '100%', border: 'none', fontSize: 11, fontWeight: 700, textAlign: 'center' }} />
                            </div>
                            <div style={{ width: 60, display: 'flex', alignItems: 'center', background: '#fff', border: '1px solid #CBD5E1', borderRadius: 20, padding: '2px 6px' }}>
                                <span style={{ fontSize: 9, fontWeight: 900, color: '#94A3B8', marginRight: 2 }}>DIR</span>
                                <input type="number" value={sp.current ? Math.round(sp.current.dir) : 90} onChange={e => { if (sp.current) { sp.current.dir = Number(e.target.value); _force(x => x + 1); } }} style={{ width: '100%', border: 'none', fontSize: 11, fontWeight: 700, textAlign: 'center' }} />
                            </div>
                        </div>
                    </div>
                </div>

                {/* Variable Monitors */}
                <div style={{ padding: '8px 12px', background: '#FFFBEB', borderBottom: '1px solid #FDE68A' }}>
                    <div style={{ fontSize: 10, fontWeight: 900, color: '#92400E', textTransform: 'uppercase', marginBottom: 4 }}>📈 SCORE & MAGIC NUMBERS</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {Object.entries(vars).length > 0 ? Object.entries(vars).map(([k, v]) => (
                            <div key={k} style={{ background: '#0F172A', border: '1px solid #334155', borderRadius: 8, padding: '4px 10px', fontSize: 12, fontWeight: 900, color: '#FCD34D' }}>
                                {k}: <span style={{ color: '#fff' }}>{typeof v === 'number' ? v.toFixed(0) : v}</span>
                            </div>
                        )) : <span style={{ fontSize: 10, color: '#94A3B8' }}>No magic numbers yet...</span>}
                    </div>
                </div>

                {Object.values(lists).some(l => l.length > 0) && (
                    <div style={{ padding: '8px 12px', background: '#F0FDF4', borderBottom: '1px solid #BBF7D0' }}>
                        <div style={{ fontSize: 10, fontWeight: 900, color: '#166534', textTransform: 'uppercase', marginBottom: 4 }}>📋 MAGIC LISTS</div>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                            {Object.entries(lists).filter(([, v]) => v.length > 0).map(([k, v]) => (
                                <div key={k} style={{ background: '#DCFCE7', border: '1.5px solid #166534', borderRadius: 10, padding: '4px 10px', fontSize: 11, fontWeight: 800 }}>
                                    <strong style={{ color: '#166534' }}>{k}</strong> ({v.length})
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Asset Management Engine */}
                <AssetTabs
                    panelTab={panelTab} setPanelTab={setPanelTab} bdrop={bdrop} spritesRef={spritesRef}
                    activeSpriteRef={activeSpriteRef} switchSprite={switchSprite} deleteSprite={deleteSprite}
                    fileInputRef={fileInputRef} handleSpriteUpload={handleSpriteUpload} clearCustomSprite={clearCustomSprite}
                    setLibMode={setLibMode} setLibCategory={setLibCategory} setSearchQuery={setSearchQuery}
                    projectSoundsRef={projectSoundsRef} projectBackdrops={projectBackdrops} BACKDROPS={BACKDROPS}
                />
            </div>
        </div>
    );
}

function AssetTabs({ panelTab, setPanelTab, bdrop, spritesRef, activeSpriteRef, switchSprite, deleteSprite,
    fileInputRef, handleSpriteUpload, clearCustomSprite, setLibMode, setLibCategory, setSearchQuery,
    projectSoundsRef, projectBackdrops, BACKDROPS }) {
    return (
        <>
            <div style={{ display: 'flex', background: '#F7FFF7', padding: '8px 12px', borderBottom: '3px solid #FFE66D', gap: 10, justifyContent: 'center' }}>
                {['sprites', 'backdrops', 'sounds'].map(tab => (
                    <button key={tab} onClick={() => setPanelTab(tab)} style={{ fontWeight: 800, fontSize: 11, background: panelTab === tab ? '#FF6B6B' : 'transparent', color: panelTab === tab ? '#fff' : '#1A535C', border: panelTab === tab ? 'none' : '1px solid #1A535C', borderRadius: 20, padding: '4px 12px', cursor: 'pointer', transition: 'all 0.2s' }}>
                        {tab === 'sprites' ? 'Sprites' : tab === 'backdrops' ? 'Backdrops' : 'Sounds'}
                    </button>
                ))}
            </div>
            <div style={{ padding: '12px', background: '#F8FAFC', flexShrink: 0, height: 180, overflowY: 'auto', overflowX: 'hidden', position: 'relative', borderBottom: '3px solid #8BC34A' }}>
                {panelTab === 'sprites' && (
                    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'flex-start' }}>
                        {spritesRef.current.map((s) => (
                            <div key={s.id} onClick={() => switchSprite(s.id)} style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, cursor: 'pointer', opacity: activeSpriteRef.current === s.id ? 1 : 0.5, transition: '.2s' }}>
                                <div style={{ width: 45, height: 45, background: '#F0F9FF', border: '2px solid', borderColor: activeSpriteRef.current === s.id ? '#FFD166' : 'transparent', borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 24, overflow: 'hidden', color: '#1A535C', fontWeight: 900 }}>
                                    {s.img ? <img src={s.img.src} width="36" alt="img" /> : 'S'}
                                </div>
                                <span style={{ fontSize: 9, fontWeight: 900, color: '#1A535C', maxWidth: 45, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
                                {spritesRef.current.length > 1 && (
                                    <button onClick={(e) => { e.stopPropagation(); deleteSprite(s.id); }} style={{ position: 'absolute', top: -4, right: -4, background: '#FF6B6B', color: '#fff', width: 16, height: 16, borderRadius: '50%', border: '2px solid #fff', fontSize: 10, lineHeight: '12px', cursor: 'pointer' }}>×</button>
                                )}
                            </div>
                        ))}
                        <button onClick={() => { setLibMode('sprite'); setLibCategory('All'); setSearchQuery(''); }} style={{ width: 45, height: 45, background: '#4ECDC4', border: '3px solid #fff', borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, cursor: 'pointer', color: '#fff', fontWeight: 900 }}>
                            +
                        </button>
                    </div>
                )}
                {panelTab === 'backdrops' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: '#F0F9FF', borderRadius: 12, border: '2px solid #4ECDC4' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                <div style={{ width: 40, height: 30, background: '#FFD166', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 900, color: '#fff' }}>WORLD</div>
                                <div style={{ display: 'flex', flexDirection: 'column' }}>
                                    <span style={{ fontSize: 11, fontWeight: 900, color: '#1A535C' }}>World</span>
                                    <span style={{ fontSize: 9, color: '#1A535C' }}>{(BACKDROPS[bdrop] || projectBackdrops.find(b => b.id === bdrop) || { name: 'Stage' }).name}</span>
                                </div>
                            </div>
                            <button onClick={() => { setLibMode('backdrop'); setLibCategory('All'); setSearchQuery(''); }} style={{ padding: '6px 12px', background: '#FF6B6B', color: '#fff', border: '2px solid #fff', borderRadius: 8, fontSize: 10, fontWeight: 900, cursor: 'pointer' }}>Change</button>
                        </div>
                    </div>
                )}
                {panelTab === 'sounds' && (
                    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'center' }}>
                        {/* Show project sounds dynamically, fall back to Kido Dev defaults */}
                        {(projectSoundsRef?.current?.length > 0
                            ? projectSoundsRef.current
                            : [
                                { id: 'meow', name: 'Meow', synthId: 'meow' },
                                { id: 'bark', name: 'Bark', synthId: 'bark' },
                                { id: 'croak', name: 'Croak', synthId: 'croak' },
                                { id: 'chomp', name: 'Chomp', synthId: 'chomp' },
                                { id: 'pop', name: 'Pop', synthId: 'pop' },
                                { id: 'dance', name: 'Dance', synthId: 'dance' },
                            ]
                        ).map(snd => (
                            <div key={snd.id} onClick={() => {
                                // Built-in synth sounds use synthId directly; CDN sounds use Audio()
                                if (snd.synthId) {
                                    playSound(snd.synthId, []);
                                } else if (snd.md5ext) {
                                    const url = `https://trampoline.turbowarp.org/assets/${snd.md5ext}`;
                                    new Audio(url).play().catch(() => { });
                                } else if (snd.src) {
                                    new Audio(snd.src).play().catch(() => { });
                                } else {
                                    playSound(snd.id, []);
                                }
                            }} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                                <div style={{ width: 42, height: 42, background: '#FFE66D', border: '2px solid #FFD166', borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, fontWeight: 900, color: '#1A535C' }}>
                                    {snd.name?.[0]?.toUpperCase() || '🎵'}
                                </div>
                                <span style={{ fontSize: 9, fontWeight: 900, color: '#1A535C', maxWidth: 50, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textAlign: 'center' }}>{snd.name}</span>
                            </div>
                        ))}
                        <button onClick={() => { setLibMode('sound'); setLibCategory('All'); setSearchQuery(''); }} style={{ width: 42, height: 42, background: '#fff', border: '3px dashed #4ECDC4', borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, cursor: 'pointer', color: '#4ECDC4', fontWeight: 900 }}>+</button>
                    </div>
                )}

            </div>
        </>
    );
}
