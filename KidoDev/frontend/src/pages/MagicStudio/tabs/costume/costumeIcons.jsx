
import React from 'react';

// ═══════════════════════════════════════════════════════════════════════════════
// SVG ICON COMPONENTS  (pixel-faithful to Scratch)
// ═══════════════════════════════════════════════════════════════════════════════

export function IconSelect({ color }) {
    return (
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M5 3L19 12L12 14L7 21V3Z" fill={color} />
        </svg>
    );
}
export function IconReshape({ color }) {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" xmlns="http://www.w3.org/2000/svg">
            <circle cx="5" cy="12" r="2.5" fill={color} stroke="none" />
            <circle cx="19" cy="12" r="2.5" fill={color} stroke="none" />
            <circle cx="12" cy="5" r="2.5" fill={color} stroke="none" />
            <circle cx="12" cy="19" r="2.5" fill={color} stroke="none" />
            <line x1="5" y1="12" x2="19" y2="12" strokeDasharray="3 2" />
            <line x1="12" y1="5" x2="12" y2="19" strokeDasharray="3 2" />
        </svg>
    );
}
export function IconBrush({ color }) {
    return (
        <svg viewBox="0 0 24 24" fill={color} xmlns="http://www.w3.org/2000/svg">
            <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zm17.71-10.21a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z" />
        </svg>
    );
}
export function IconEraser({ color }) {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" xmlns="http://www.w3.org/2000/svg">
            <path d="M20 20H7L3 16l10-10 8 8-4 4" />
            <path d="M6.5 17.5l4-4" />
        </svg>
    );
}
export function IconFill({ color }) {
    return (
        <svg viewBox="0 0 24 24" fill={color} xmlns="http://www.w3.org/2000/svg">
            <path d="M16.56 8.94L7.62 0 6.21 1.41l2.38 2.38-5.15 5.15a1.49 1.49 0 0 0 0 2.12l5.5 5.5c.29.29.68.44 1.06.44s.77-.15 1.06-.44l5.5-5.5c.59-.58.59-1.53 0-2.12zM5.21 10L10 5.21 14.79 10H5.21z" />
            <path d="M20 19c0 1.1-2 3-2 3s-2-1.9-2-3a2 2 0 0 1 4 0z" />
        </svg>
    );
}
export function IconText({ color }) {
    return (
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <text x="3" y="20" fontSize="19" fontWeight="bold" fontFamily="serif" fill={color}>T</text>
        </svg>
    );
}
export function IconLine({ color }) {
    return (
        <svg viewBox="0 0 24 24" stroke={color} strokeWidth="2.5" strokeLinecap="round" xmlns="http://www.w3.org/2000/svg">
            <line x1="4" y1="20" x2="20" y2="4" />
        </svg>
    );
}
export function IconCircle({ color }) {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" xmlns="http://www.w3.org/2000/svg">
            <circle cx="12" cy="12" r="9" />
        </svg>
    );
}
export function IconRect({ color }) {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" xmlns="http://www.w3.org/2000/svg">
            <rect x="3" y="5" width="18" height="14" rx="1.5" />
        </svg>
    );
}
// Bitmap-specific filled versions
export function IconCircleFilled({ color }) {
    return (
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <circle cx="12" cy="12" r="9" fill={color} />
        </svg>
    );
}
export function IconRectFilled({ color }) {
    return (
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <rect x="3" y="5" width="18" height="14" rx="1.5" fill={color} />
        </svg>
    );
}
export function IconSelectBitmap({ color }) {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeDasharray="3 2" xmlns="http://www.w3.org/2000/svg">
            <rect x="3" y="3" width="18" height="18" rx="1" />
            <path d="M14 14l5 5" stroke={color} strokeWidth="2" />
            <path d="M14 14h4v4" stroke={color} strokeWidth="2" fill="none" />
        </svg>
    );
}
