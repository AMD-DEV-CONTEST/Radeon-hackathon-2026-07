// SalutingCat.jsx — Fullscreen Level Complete Video Animation
import React, { useEffect, useRef } from 'react';

const DURATION_MS = 3800; // Duration of level-complete video sequence

export default function SaluteSprite({ active, onDone }) {
    const videoRef = useRef(null);

    useEffect(() => {
        if (!active) return;

        if (videoRef.current) {
            videoRef.current.currentTime = 0;
            videoRef.current.play().catch(err => console.warn('[LevelCompleteVideo] Play error:', err));
        }

        const timer = setTimeout(() => {
            if (typeof onDone === 'function') onDone();
        }, DURATION_MS);

        return () => clearTimeout(timer);
    }, [active, onDone]);

    if (!active) return null;

    return (
        <div
            style={{
                position: 'fixed',
                top: 0,
                left: 0,
                width: '100vw',
                height: '100vh',
                zIndex: 99999,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: '#000000',
                overflow: 'hidden',
            }}
        >
            <video
                ref={videoRef}
                src="/assets/videos/level-complete.webm"
                autoPlay
                playsInline
                muted
                onEnded={() => onDone && onDone()}
                style={{
                    width: '100vw',
                    height: '100vh',
                    objectFit: 'cover',
                }}
            />
        </div>
    );
}