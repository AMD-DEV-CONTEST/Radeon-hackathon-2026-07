import React from 'react';
import { CodeTab } from './tabs/CodeTab';
import { CostumesTab } from './tabs/costume/CostumesTab';
import { SoundTab } from './tabs/SoundTab';

/**
 * WorkspaceTabs Component
 * 
 * Parent router for code/costume/sound tabs.
 * Renders tab buttons and manages active tab state.
 * Passes down all necessary props to child tab components.
 */
export function WorkspaceTabs({ 
    activeTab, 
    setTab,
    blocklyDiv,
    wsRef,
    isMobile,
    activeSprite,
    sprites,
    sp,
    spritesRef,
    activeSpriteRef,
    projectSoundsRef,
    _force,
    addLog,
    fileInputRef,
    setLibMode
}) {
    const tabs = [
        { id: 'code', label: '🧩 Code' },
        { id: 'costumes', label: '🎨 Costumes' },
        { id: 'sounds', label: '🎵 Sounds' }
    ];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
            {/* Tab Buttons */}
            <div style={{ display: 'flex', background: '#E8F5E9', padding: '0 10px', flexShrink: 0, gap: 5, borderBottom: '2px solid #8BC34A' }}>
                {tabs.map(t => (
                    <button
                        key={t.id}
                        onClick={() => setTab(t.id)}
                        style={{
                            padding: '10px 20px',
                            background: activeTab === t.id ? '#FFFFFF' : 'transparent',
                            color: activeTab === t.id ? '#2E7D32' : '#558B2F',
                            border: 'none',
                            borderTopLeftRadius: 8,
                            borderTopRightRadius: 8,
                            fontSize: 12,
                            fontWeight: 800,
                            cursor: 'pointer',
                            borderBottom: activeTab === t.id ? '3px solid #8BC34A' : '3px solid transparent',
                            transition: 'all 0.2s',
                            marginTop: '4px'
                        }}
                    >
                        {t.label}
                    </button>
                ))}
            </div>

            {/* Tab Content */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' }}>
                <div style={{ display: activeTab === 'code' ? 'flex' : 'none', flex: 1, flexDirection: 'column', overflow: 'hidden', height: '100%' }}>
                    <CodeTab 
                        blocklyDiv={blocklyDiv}
                        wsRef={wsRef}
                        isMobile={isMobile}
                        activeSprite={activeSprite}
                        sprites={sprites}
                    />
                </div>
                
                {activeTab === 'costumes' && (
                    <CostumesTab 
                        sp={sp}
                        activeSpriteRef={activeSpriteRef}
                        spritesRef={spritesRef}
                        _force={_force}
                        addLog={addLog}
                        fileInputRef={fileInputRef}
                    />
                )}
                
                {activeTab === 'sounds' && (
                    <SoundTab 
                        sp={sp}
                        projectSoundsRef={projectSoundsRef}
                        _force={_force}
                        addLog={addLog}
                        setLibMode={setLibMode}
                    />
                )}
            </div>
        </div>
    );
}

// Export tab components for backwards compatibility if needed
export { CodeTab } from './tabs/CodeTab';
export { CostumesTab } from './tabs/costume/CostumesTab';
export { SoundTab } from './tabs/SoundTab';
