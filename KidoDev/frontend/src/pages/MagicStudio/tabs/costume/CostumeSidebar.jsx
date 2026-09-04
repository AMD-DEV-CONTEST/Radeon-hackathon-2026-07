
import React from 'react';
import { SC, addBtnStyle } from './costumeToolbarUI';

/**
 * CostumeSidebar – Column 1: costume thumbnail tray with paint-new / upload buttons.
 */
export function CostumeSidebar({
    costumes, activeIdx, switchCostume, deleteCostume,
    paintNew, handleUpload,
}) {
    return (
        <div style={{
            width: 106, background: '#F9F9F9',
            borderRight: `1px solid ${SC.border}`,
            display: 'flex', flexDirection: 'column',
            overflowY: 'auto', flexShrink: 0,
        }}>

            {costumes.map((c, i) => (
                <div
                    key={c.id}
                    onClick={() => switchCostume(i)}
                    style={{
                        flexShrink: 0, padding: '8px 6px', cursor: 'pointer',
                        position: 'relative',
                        background: activeIdx === i ? SC.purpleLight : 'transparent',
                        borderLeft: `3px solid ${activeIdx === i ? SC.purple : 'transparent'}`,
                        borderBottom: `1px solid ${SC.border}`,
                        transition: 'background 0.1s',
                    }}
                >
                    {/* Index number */}
                    <div style={{
                        fontSize: 9, fontWeight: 700,
                        color: activeIdx === i ? SC.purple : '#b0b8c8', marginBottom: 4,
                    }}>{i + 1}</div>

                    {/* Thumbnail box */}
                    <div style={{
                        height: 64,
                        background: `repeating-conic-gradient(#D9E3F0 0% 25%, #fff 0% 50%) 0 0 / 10px 10px`,
                        border: `1px solid ${SC.border}`, borderRadius: 4,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        overflow: 'hidden',
                    }}>
                        {c.img
                            ? <img src={c.img.src} style={{ maxWidth: '90%', maxHeight: '90%', objectFit: 'contain' }} alt="" />
                            : <span style={{ fontSize: 26 }}>{c.emoji || '🎨'}</span>
                        }
                    </div>

                    {/* Name */}
                    <div style={{
                        fontSize: 10, textAlign: 'center', color: SC.text,
                        marginTop: 4, overflow: 'hidden',
                        textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>{c.name}</div>

                    {/* Delete × button */}
                    {costumes.length > 1 && (
                        <button
                            onClick={(e) => deleteCostume(e, i)}
                            style={{
                                position: 'absolute', top: 2, right: 2,
                                width: 18, height: 18, borderRadius: '50%',
                                background: SC.del, color: '#fff',
                                border: '2px solid #fff',
                                fontSize: 12, fontWeight: 900,
                                cursor: 'pointer',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                lineHeight: 1, padding: 0,
                            }}
                        >×</button>
                    )}
                </div>
            ))}

            {/* Add costume buttons */}
            <div style={{
                padding: '8px 6px',
                display: 'flex', gap: 4, justifyContent: 'center',
                borderTop: `1px solid ${SC.border}`, marginTop: 'auto', flexShrink: 0,
            }}>
                <button
                    title="Paint new costume"
                    onClick={paintNew}
                    style={addBtnStyle}
                >🖌️</button>
                <label
                    title="Upload costume"
                    style={{ ...addBtnStyle, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}
                >
                    📤
                    <input type="file" hidden accept="image/*" onChange={handleUpload} />
                </label>
            </div>
        </div>
    );
}
