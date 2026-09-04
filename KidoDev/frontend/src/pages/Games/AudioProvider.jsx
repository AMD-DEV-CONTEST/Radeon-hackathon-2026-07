import React, { createContext, useContext, useEffect, useState } from "react";

const AudioContext = createContext(null);

export const useAudio = () => {
    const ctx = useContext(AudioContext);
    if (!ctx) throw new Error("useAudio must be used inside AudioProvider");
    return ctx;
};

let _audio = null;
let _hasStarted = false;

function getAudio() {
    if (!_audio) {
        _audio = new Audio("/assets/audio/bg-audio.mp3");
        _audio.loop = true;
        _audio.volume = 0.4;
        _audio.addEventListener('error', () => {
            console.error("❌ Audio failed to load — check path: /assets/audio/bg-audio.mp3");
        });
    }
    return _audio;
}

export const AudioProvider = ({ children }) => {
    const [isMuted, setIsMuted] = useState(false);

    // ✅ Stop music completely when leaving /games route
    useEffect(() => {
        return () => {
            const audio = getAudio();
            audio.pause();
            audio.currentTime = 0;
            _hasStarted = false;
            console.log("🛑 Left /games — music stopped");
        };
    }, []);

    const play = () => {
        const audio = getAudio();
        if (_hasStarted) return;
        audio.play()
            .then(() => {
                _hasStarted = true;
                console.log("✅ Music started");
            })
            .catch((err) => {
                console.error("❌ play() blocked:", err.name, err.message);
            });
    };

    // ✅ Pause without resetting — used when returning to hub between games
    const pause = () => {
        const audio = getAudio();
        audio.pause();
        _hasStarted = false;
        console.log("⏸️ Music paused");
    };

    const stop = () => {
        const audio = getAudio();
        audio.pause();
        audio.currentTime = 0;
        _hasStarted = false;
        console.log("🛑 Music stopped");
    };

    const mute = () => { getAudio().muted = true; setIsMuted(true); };
    const unmute = () => { getAudio().muted = false; setIsMuted(false); };

    return (
        <AudioContext.Provider value={{ play, pause, stop, mute, unmute, isMuted }}>
            {children}
        </AudioContext.Provider>
    );
};

export default AudioProvider;