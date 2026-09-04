
import React from 'react';
import {
    IconSelect, IconReshape, IconBrush, IconEraser, IconFill,
    IconText, IconLine, IconCircle, IconRect,
    IconCircleFilled, IconRectFilled, IconSelectBitmap,
} from './costumeIcons';

// ─── Scratch colour palette ────────────────────────────────────────────────────
export const SC = {
    white: '#FFFFFF',
    toolBg: '#F9F9F9',
    toolBdr: '#D9E3F0',
    toolSel: '#855CD6',      // Scratch purple (active tool bg)
    toolSelBg: '#855CD6',
    toolSelIcon: '#FFFFFF',
    canvasBg: '#FFFFFF',
    del: '#FF6680',
    text: '#575E75',
    border: '#D9E3F0',
    tabBar: '#E6F0FF',
    purple: '#855CD6',
    purpleLight: '#EDE8F5',
    thumbActive: '#D9E3F0',
    thumbBorder: '#855CD6',
};

// Checkerboard for transparent canvas background (matches Scratch exactly)
export const CHECKER_BG = `
  repeating-conic-gradient(#D9E3F0 0% 25%, #FFFFFF 0% 50%)
  0 0 / 16px 16px
`.trim();

// ─── VECTOR tool definitions ───────────────────────────────────────────────────
export const VECTOR_TOOLS = [
    { id: 'select', label: 'Select', Icon: IconSelect },
    { id: 'reshape', label: 'Reshape', Icon: IconReshape },
    { id: 'brush', label: 'Brush', Icon: IconBrush },
    { id: 'eraser', label: 'Eraser', Icon: IconEraser },
    { id: 'fill', label: 'Fill', Icon: IconFill },
    { id: 'text', label: 'Text', Icon: IconText },
    { id: 'line', label: 'Line', Icon: IconLine },
    { id: 'circle', label: 'Circle', Icon: IconCircle },
    { id: 'rect', label: 'Rect', Icon: IconRect },
];

// ─── BITMAP tool definitions ──────────────────────────────────────────────────
export const BITMAP_TOOLS = [
    { id: 'brush', label: 'Brush', Icon: IconBrush },
    { id: 'line', label: 'Line', Icon: IconLine },
    { id: 'circle', label: 'Circle', Icon: IconCircleFilled },
    { id: 'rect', label: 'Rect', Icon: IconRectFilled },
    { id: 'text', label: 'Text', Icon: IconText },
    { id: 'select', label: 'Select', Icon: IconSelectBitmap },
    { id: 'eraser', label: 'Eraser', Icon: IconEraser },
];

// ─── Reusable toolbar icon button with purple selection state ─────────────────
export function ToolBtn({ toolDef, selected, onClick }) {
    const { id, label, Icon } = toolDef;
    const iconColor = selected ? SC.toolSelIcon : SC.text;
    return (
        <button
            title={label}
            onClick={() => onClick(id)}
            style={{
                width: 40, height: 40,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: selected ? SC.toolSelBg : 'transparent',
                border: '2px solid transparent',
                borderRadius: 8,
                cursor: 'pointer',
                padding: 5,
                transition: 'background 0.12s',
            }}
        >
            <div style={{ width: 26, height: 26 }}>
                <Icon color={iconColor} />
            </div>
        </button>
    );
}

// ─── Small top-bar action button (Group / Undo / Delete etc.) ─────────────────
export function ActionBtn({ icon, label, onClick, disabled = false, danger = false }) {
    return (
        <button
            title={label}
            onClick={onClick}
            disabled={disabled}
            style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center',
                gap: 2, background: 'none', border: 'none',
                cursor: disabled ? 'not-allowed' : 'pointer',
                opacity: disabled ? 0.35 : 1,
                padding: '4px 6px', borderRadius: 6,
                color: danger ? SC.del : SC.text,
                fontSize: 10, fontWeight: 700,
                textTransform: 'uppercase', letterSpacing: 0.4,
                transition: 'opacity 0.12s',
                userSelect: 'none',
            }}
        >
            <span style={{ fontSize: 18, lineHeight: 1 }}>{icon}</span>
            <span>{label}</span>
        </button>
    );
}

// ─── Vertical separator ───────────────────────────────────────────────────────
export const Sep = () => (
    <div style={{ width: 1, alignSelf: 'stretch', background: SC.border, margin: '0 6px', flexShrink: 0 }} />
);

// ─── Colour picker pill (Fill / Outline) ─────────────────────────────────────
export function ColorPill({ value, onChange, onClear, label }) {
    const isTransparent = value === 'transparent';
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: '#aaa' }}>{label}</span>
            <div style={{
                display: 'flex', alignItems: 'center', gap: 2,
                border: `1.5px solid ${SC.border}`, borderRadius: 20,
                padding: '2px 8px', background: SC.white,
            }}>
                {/* Colour swatch – gradient for bitmap mode when value is 'gradient' */}
                <div style={{ position: 'relative', width: 26, height: 26 }}>
                    {value === 'gradient'
                        ? <div style={{ width: 26, height: 26, borderRadius: '50%', background: 'conic-gradient(red,yellow,lime,cyan,blue,magenta,red)', cursor: 'pointer' }} />
                        : (
                            <>
                                <input
                                    type="color"
                                    value={isTransparent ? '#ffffff' : value}
                                    onChange={e => onChange(e.target.value)}
                                    style={{ width: 26, height: 26, border: 'none', background: 'none', cursor: 'pointer', padding: 0, borderRadius: '50%', overflow: 'hidden' }}
                                />
                                {isTransparent && (
                                    /* Red slash overlay for transparent */
                                    <div style={{
                                        position: 'absolute', inset: 0, pointerEvents: 'none',
                                        borderRadius: '50%', border: `1px solid ${SC.border}`,
                                        background: 'linear-gradient(135deg, transparent 47%, #FF6680 47%, #FF6680 53%, transparent 53%)',
                                    }} />
                                )}
                            </>
                        )
                    }
                </div>
                {/* Transparent toggle */}
                <button
                    onClick={onClear}
                    title="No colour"
                    style={{
                        border: 'none', background: 'none', cursor: 'pointer',
                        fontSize: 16, color: isTransparent ? SC.del : '#bbb',
                        fontWeight: 900, padding: '0 2px', lineHeight: 1,
                    }}
                >∅</button>
            </div>
        </div>
    );
}

// ─── Shared static button styles ──────────────────────────────────────────────
export const addBtnStyle = {
    flex: 1, height: 32,
    background: '#fff', border: `1px solid ${SC.border}`,
    borderRadius: 6, cursor: 'pointer', fontSize: 16,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
};
export const iconBtnStyle = {
    width: 30, height: 30, borderRadius: 6,
    border: `1.5px solid ${SC.border}`,
    background: SC.white, cursor: 'pointer',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    flexShrink: 0,
};
export const zoomBtnStyle = {
    width: 28, height: 28, borderRadius: 6,
    border: `1px solid ${SC.border}`,
    background: SC.white, cursor: 'pointer',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
};
