import React from 'react';

/**
 * CodeTab Component
 * 
 * Renders Blockly workspace for visual programming.
 * Receives blocklyDiv ref to mount Blockly into.
 * Receives wsRef to allow the "Clear All" button to call wsRef.current.clear().
 */
export function CodeTab({ blocklyDiv, wsRef, isMobile, activeSprite, sprites }) {
    const handleClearAll = () => {
        // Guard: ensure the workspace instance exists before clearing
        if (!wsRef || !wsRef.current) return;
        wsRef.current.clear();
    };

    return (
        <div style={{
            display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden',
            position: 'relative',
        }}>
            <div style={{ 
                padding: '5px 12px', background: '#F0F9FF', 
                borderBottom: '2px solid #4ECDC4', color: '#1A535C', 
                fontSize: 11, fontWeight: 900, flexShrink: 0,
                display: 'flex', alignItems: 'center', justifyContent: 'space-between'
            }}>
                <span>🧩 {activeSprite?.name || 'Sprite'} - Drag blocks to create your magic!</span>
                <button
                    onClick={handleClearAll}
                    title="Delete all blocks"
                    style={{
                        background: '#FF6B6B',
                        color: '#fff',
                        border: '2px solid #fff',
                        borderRadius: 8,
                        padding: '3px 10px',
                        fontSize: 11,
                        fontWeight: 900,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                        boxShadow: '0 2px 6px rgba(255,107,107,0.4)',
                        transition: 'opacity 0.2s',
                    }}
                    onMouseEnter={e => e.currentTarget.style.opacity = '0.8'}
                    onMouseLeave={e => e.currentTarget.style.opacity = '1'}
                >
                    🗑️ Clear All
                </button>
            </div>
            <div ref={blocklyDiv} style={{ flex: 1, overflow: 'hidden' }} />
        </div>
    );
}
