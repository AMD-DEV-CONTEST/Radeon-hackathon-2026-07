
import React from 'react';
import {
    SC, ActionBtn, Sep, ColorPill,
    iconBtnStyle,
} from './costumeToolbarUI';

/**
 * CostumeToolbars – Toolbar Row 1 (name, undo/redo, group/layer)
 *                    Toolbar Row 2 (fill/outline colors, copy/paste/delete, flip)
 */
export function CostumeToolbars({
    costumeName, changeName,
    isVector, hasSelection,
    fillColor, setFillColor,
    strokeColor, setStrokeColor,
    strokeWidth, setStrokeWidth,
    fabricRef, clipboardRef,
    handleUndo, handleRedo, bitmapUndo, bitmapRedo,
    groupSel, ungroupSel, sendLayer,
    handleCopy, handlePaste, handleDeleteSel,
    flip, bitmapFlip,
}) {
    return (
        <>
            {/* ── Toolbar Row 1 ──────────────────────────────────────────────── */}
            <div style={{
                background: SC.white,
                borderBottom: `1px solid ${SC.border}`,
                display: 'flex', alignItems: 'center',
                padding: '5px 12px', gap: 6, flexShrink: 0, flexWrap: 'wrap',
                minHeight: 48,
            }}>
                {/* Costume label + name input */}
                <span style={{ fontSize: 12, fontWeight: 700, color: '#aaa', flexShrink: 0 }}>Costume</span>
                <input
                    value={costumeName}
                    onChange={changeName}
                    style={{
                        border: `1.5px solid ${SC.border}`, borderRadius: 14,
                        padding: '4px 12px', fontSize: 13, fontWeight: 600,
                        outline: 'none', width: 110, color: SC.text,
                        background: SC.white,
                    }}
                />
                <Sep />

                {/* Undo / Redo */}
                <button
                    title="Undo (Ctrl+Z)"
                    onClick={isVector ? handleUndo : bitmapUndo}
                    style={iconBtnStyle}
                >
                    {/* Left-curved arrow */}
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke={SC.purple} strokeWidth="2.5" strokeLinecap="round">
                        <path d="M3 10h10a6 6 0 0 1 0 12H9" />
                        <path d="M3 10l4-4M3 10l4 4" />
                    </svg>
                </button>
                <button
                    title="Redo (Ctrl+Y)"
                    onClick={isVector ? handleRedo : bitmapRedo}
                    style={iconBtnStyle}
                >
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke={SC.purple} strokeWidth="2.5" strokeLinecap="round">
                        <path d="M21 10H11a6 6 0 0 0 0 12h4" />
                        <path d="M21 10l-4-4M21 10l-4 4" />
                    </svg>
                </button>

                {/* Vector-only controls */}
                {isVector && (
                    <>
                        <Sep />
                        <ActionBtn icon="🔗" label="Group" onClick={groupSel} disabled={!hasSelection} />
                        <ActionBtn icon="⛓" label="Ungroup" onClick={ungroupSel} disabled={!hasSelection} />
                        <Sep />
                        <ActionBtn icon="⬆" label="Forward" onClick={() => sendLayer('forward')} disabled={!hasSelection} />
                        <ActionBtn icon="⬇" label="Backward" onClick={() => sendLayer('backward')} disabled={!hasSelection} />
                        <ActionBtn icon="⏫" label="Front" onClick={() => sendLayer('front')} disabled={!hasSelection} />
                        <ActionBtn icon="⏬" label="Back" onClick={() => sendLayer('back')} disabled={!hasSelection} />
                    </>
                )}
            </div>

            {/* ── Toolbar Row 2 ──────────────────────────────────────────────── */}
            <div style={{
                background: SC.white,
                borderBottom: `1px solid ${SC.border}`,
                display: 'flex', alignItems: 'center',
                padding: '3px 12px', gap: 8, flexShrink: 0, flexWrap: 'wrap',
                minHeight: 44,
            }}>
                {/* Fill colour (both modes) */}
                {/* FIX: removed o.type !== 'path' && o.type !== 'line' filter —
                   always apply fill to every selected object, matching Scratch's
                   paint-bucket behavior (same fix as useVectorCanvas fill tool). */}
                <ColorPill
                    label="Fill"
                    value={fillColor}
                    onChange={(c) => {
                        setFillColor(c);
                        if (isVector && fabricRef.current && hasSelection) {
                            fabricRef.current.getActiveObjects().forEach(o => {
                                o.set('fill', c);
                            });
                            fabricRef.current.renderAll();
                        }
                    }}
                    onClear={() => setFillColor('transparent')}
                />

                {/* Outline – vector mode only */}
                {isVector && (
                    <>
                        <ColorPill
                            label="Outline"
                            value={strokeColor}
                            onChange={(c) => {
                                setStrokeColor(c);
                                if (fabricRef.current && hasSelection) {
                                    fabricRef.current.getActiveObjects().forEach(o => o.set('stroke', c));
                                    fabricRef.current.renderAll();
                                }
                            }}
                            onClear={() => setStrokeColor('transparent')}
                        />
                        <input
                            type="number" min={0} max={50}
                            value={strokeWidth}
                            onChange={e => {
                                const v = Number(e.target.value);
                                setStrokeWidth(v);
                                if (fabricRef.current && hasSelection) {
                                    fabricRef.current.getActiveObjects().forEach(o => o.set('strokeWidth', v));
                                    fabricRef.current.renderAll();
                                }
                            }}
                            style={{
                                width: 46, height: 28, textAlign: 'center',
                                border: `1.5px solid ${SC.border}`, borderRadius: 8,
                                fontWeight: 700, outline: 'none', fontSize: 13,
                                color: SC.text,
                            }}
                        />
                    </>
                )}

                <Sep />

                {/* Copy / Paste / Delete */}
                <ActionBtn
                    icon="📄" label="Copy"
                    onClick={isVector ? handleCopy : undefined}
                    disabled={isVector ? !hasSelection : true}
                />
                <ActionBtn
                    icon="📋" label="Paste"
                    onClick={isVector ? handlePaste : undefined}
                    disabled={isVector ? !clipboardRef.current : true}
                />
                <ActionBtn
                    icon="🗑" label="Delete"
                    onClick={isVector ? handleDeleteSel : undefined}
                    disabled={isVector ? !hasSelection : true}
                    danger
                />

                <Sep />

                {/* Flip */}
                <ActionBtn
                    icon={<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke={SC.purple} strokeWidth="2" strokeLinecap="round"><path d="M3 12h18M9 6l-6 6 6 6M15 6l6 6-6 6" /></svg>}
                    label="Flip H"
                    onClick={() => isVector ? flip('h') : bitmapFlip('h')}
                />
                <ActionBtn
                    icon={<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke={SC.purple} strokeWidth="2" strokeLinecap="round"><path d="M12 3v18M6 9l6-6 6 6M6 15l6 6 6-6" /></svg>}
                    label="Flip V"
                    onClick={() => isVector ? flip('v') : bitmapFlip('v')}
                />
            </div>
        </>
    );
}
