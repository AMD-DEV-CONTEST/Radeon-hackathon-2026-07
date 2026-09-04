
import React from 'react';
import {
    SC, CHECKER_BG, VECTOR_TOOLS, BITMAP_TOOLS,
    ToolBtn, zoomBtnStyle,
} from './costumeToolbarUI';

/**
 * CostumeCanvasPanel – Column 2 (tool palette) + Column 3 (toolbars + canvas + bottom bar).
 *
 * `children` is rendered inside Column 3 before the canvas area — this is where
 * <CostumeToolbars /> should be placed by the parent to maintain the original
 * layout (toolbars at top of Column 3).
 */
export function CostumeCanvasPanel({
    children,
    isVector, tool, setTool,
    cvRef, zoom, setZoom,
    convertToBitmap, convertToVector,
}) {
    const tools = isVector ? VECTOR_TOOLS : BITMAP_TOOLS;

    return (
        <>
            {/* ══════════════════════════════════════════════════════════════════════
          COLUMN 2 — Tool palette
          2-column grid matching Scratch's left tool panel
      ══════════════════════════════════════════════════════════════════════ */}
            <div style={{
                width: 90, background: SC.toolBg,
                borderRight: `1px solid ${SC.border}`,
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', padding: '10px 4px',
                gap: 4, flexShrink: 0, overflowY: 'auto',
            }}>
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: 4, width: '100%',
                }}>
                    {tools.map(t => (
                        <ToolBtn
                            key={t.id}
                            toolDef={t}
                            selected={tool === t.id}
                            onClick={setTool}
                        />
                    ))}
                </div>
            </div>

            {/* ══════════════════════════════════════════════════════════════════════
          COLUMN 3 — Canvas area + top toolbars
      ══════════════════════════════════════════════════════════════════════ */}
            <div style={{
                flex: 1, display: 'flex', flexDirection: 'column',
                minWidth: 0, background: '#F9F9F9',
            }}>

                {/* Toolbars (injected by parent as children) */}
                {children}

                {/* ── Canvas area ────────────────────────────────────────────────── */}
                <div style={{
                    flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: '#F9F9F9', overflow: 'hidden', position: 'relative',
                }}>
                    {/* Zoom-scaled canvas wrapper */}
                    <div style={{
                        position: 'relative',
                        width: 480, height: 360,
                        transform: `scale(${zoom})`,
                        transformOrigin: 'center center',
                        border: `1px solid ${SC.border}`,
                        borderRadius: 8,
                        boxShadow: '0 2px 10px rgba(0,0,0,0.1)',
                        background: CHECKER_BG,
                        overflow: 'hidden',
                    }}>
                        {/* Single <canvas> used by both Fabric (vector) and 2D (bitmap) */}
                        <canvas
                            ref={cvRef}
                            width={480}
                            height={360}
                            style={{ display: 'block', borderRadius: 8 }}
                        />
                    </div>
                </div>

                {/* ── Bottom bar: Convert button + Zoom controls ──────────────────── */}
                <div style={{
                    background: SC.white,
                    borderTop: `1px solid ${SC.border}`,
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '6px 16px', flexShrink: 0,
                }}>
                    {/* Convert to Bitmap / Vector */}
                    <button
                        onClick={isVector ? convertToBitmap : convertToVector}
                        style={{
                            display: 'flex', alignItems: 'center', gap: 8,
                            background: SC.purple, color: '#fff',
                            border: 'none', borderRadius: 20,
                            padding: '8px 16px', fontSize: 13, fontWeight: 700,
                            cursor: 'pointer',
                            boxShadow: '0 2px 6px rgba(133,92,214,0.35)',
                            transition: 'transform 0.1s, box-shadow 0.1s',
                        }}
                        onMouseDown={e => e.currentTarget.style.transform = 'scale(0.96)'}
                        onMouseUp={e => e.currentTarget.style.transform = 'scale(1)'}
                    >
                        {/* Image icon */}
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="white">
                            <rect x="3" y="3" width="18" height="14" rx="2" fill="none" stroke="white" strokeWidth="2" />
                            <path d="M3 14l4-4 4 4 4-5 4 5" stroke="white" strokeWidth="1.5" fill="none" strokeLinejoin="round" />
                            <circle cx="8" cy="8" r="1.5" fill="white" />
                        </svg>
                        {isVector ? 'Convert to Bitmap' : 'Convert to Vector'}
                    </button>

                    {/* Zoom controls */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <button
                            onClick={() => setZoom(z => Math.max(0.25, +(z - 0.25).toFixed(2)))}
                            style={zoomBtnStyle}
                            title="Zoom out"
                        >
                            <svg viewBox="0 0 24 24" width="16" height="16" stroke={SC.purple} strokeWidth="2" fill="none">
                                <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="8" y1="11" x2="14" y2="11" />
                            </svg>
                        </button>
                        <span style={{ fontSize: 12, fontWeight: 700, color: SC.text, minWidth: 40, textAlign: 'center' }}>
                            {Math.round(zoom * 100)}%
                        </span>
                        <button
                            onClick={() => setZoom(z => Math.min(4, +(z + 0.25).toFixed(2)))}
                            style={zoomBtnStyle}
                            title="Zoom in"
                        >
                            <svg viewBox="0 0 24 24" width="16" height="16" stroke={SC.purple} strokeWidth="2" fill="none">
                                <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
                                <line x1="11" y1="8" x2="11" y2="14" /><line x1="8" y1="11" x2="14" y2="11" />
                            </svg>
                        </button>
                        <button
                            onClick={() => setZoom(1)}
                            style={zoomBtnStyle}
                            title="Reset zoom"
                        >
                            <svg viewBox="0 0 24 24" width="16" height="16" stroke={SC.purple} strokeWidth="2" fill="none">
                                <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
                                <line x1="8" y1="11" x2="14" y2="11" />
                                <line x1="11" y1="8" x2="11" y2="14" opacity="0" />
                                <text x="7" y="15" fontSize="9" fontWeight="bold" fill={SC.purple} stroke="none">1:1</text>
                            </svg>
                        </button>
                    </div>
                </div>

            </div> {/* end Column 3 */}
        </>
    );
}
