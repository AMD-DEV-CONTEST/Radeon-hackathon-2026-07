/**
 * soundEngine.js
 * 
 * High-fidelity Web Audio Synthesizer and Player for Magic Studio.
 * Features:
 *  1. Global AudioContext singleton with automatic user-gesture unlocking.
 *  2. Rich, realistic, 100% offline procedural synthesis for ALL standard sounds.
 *  3. Seamless fallback to synthesize custom sounds if network requests or CORS fail.
 */

import { getCleanAssetUrl } from './constants';

// --- 1. GLOBAL AUDIOCONTEXT SINGLETON & AUTO-UNLOCK ---
let globalAudioContext = null;

export function getAudioContext() {
    if (typeof window === 'undefined') return null;
    if (!globalAudioContext) {
        globalAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (globalAudioContext.state === 'suspended') {
        globalAudioContext.resume().catch(() => { });
    }
    return globalAudioContext;
}

// Auto-unlock AudioContext on first click/touch/keydown to satisfy browser policies
if (typeof window !== 'undefined') {
    const unlock = () => {
        getAudioContext();
        window.removeEventListener('click', unlock);
        window.removeEventListener('touchstart', unlock);
        window.removeEventListener('keydown', unlock);
    };
    window.addEventListener('click', unlock, { passive: true });
    window.addEventListener('touchstart', unlock, { passive: true });
    window.addEventListener('keydown', unlock, { passive: true });
}

// --- 2. HELPERS ---
export function midiToFreq(note) {
    return 440 * Math.pow(2, (note - 69) / 12);
}

export function playNote(noteNum, beats, tempoRef) {
    try {
        const bpm = tempoRef?.current || 120;
        const durationMs = (60 / bpm) * beats * 1000;
        const ac = getAudioContext();
        if (!ac) return 200;

        const o = ac.createOscillator();
        const gn = ac.createGain();
        o.connect(gn);
        gn.connect(ac.destination);

        o.type = 'triangle';
        o.frequency.setValueAtTime(midiToFreq(noteNum), ac.currentTime);
        gn.gain.setValueAtTime(0.3, ac.currentTime);
        gn.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + durationMs / 1000);

        o.start();
        o.stop(ac.currentTime + durationMs / 1000);
        return durationMs;
    } catch (e) {
        return 200;
    }
}

const CDN_ANIMAL_SOUNDS = {
    meow: 'https://trampoline.turbowarp.org/assets/83c36b803e3a4c5d9708a3d51726a760.wav',
    bark: 'https://trampoline.turbowarp.org/assets/601c10d32f50882645163013b827e212.wav',
    pop: 'https://trampoline.turbowarp.org/assets/83a9787d4cb6f3b7632b4ddfebf74367.wav',
    laser: 'https://trampoline.turbowarp.org/assets/8e89f81640165c0d50731f9076f7f6f5.wav',
    coin: 'https://trampoline.turbowarp.org/assets/751d9e2621453982e5d7d9a102a0a2f5.wav',
    chomp: 'https://trampoline.turbowarp.org/assets/6e19036c845f94901f4a475d68d1b116.wav',
    dance: 'https://trampoline.turbowarp.org/assets/83f6087595304323c21a1158864700d1.wav',
    drum: 'https://trampoline.turbowarp.org/assets/0a49c95d562f7902cf7252086e7a2503.wav',
    croak: 'https://trampoline.turbowarp.org/assets/1e6ff34eaa5d48ada6583a56e96a1fe0.wav',
    moo: 'https://trampoline.turbowarp.org/assets/660c18d18451f112c8227b687f3b89b1.wav',
    roar: 'https://trampoline.turbowarp.org/assets/63445851410986967756f71d5300f2e0.wav',
    duck: 'https://trampoline.turbowarp.org/assets/f5207c4587a8e235a90d81c3c959445a.wav',

    // Dropdown variations
    'meow (cat)': 'https://trampoline.turbowarp.org/assets/83c36b803e3a4c5d9708a3d51726a760.wav',
    'bark (dog)': 'https://trampoline.turbowarp.org/assets/601c10d32f50882645163013b827e212.wav',
    'croak (frog)': 'https://trampoline.turbowarp.org/assets/1e6ff34eaa5d48ada6583a56e96a1fe0.wav',
    'roar (lion)': 'https://trampoline.turbowarp.org/assets/63445851410986967756f71d5300f2e0.wav',
    'moo (cow)': 'https://trampoline.turbowarp.org/assets/660c18d18451f112c8227b687f3b89b1.wav',
    'dance music': 'https://trampoline.turbowarp.org/assets/83f6087595304323c21a1158864700d1.wav',
    'jungle': 'https://trampoline.turbowarp.org/assets/83f6087595304323c21a1158864700d1.wav'
};

// --- 3. HIGH-FIDELITY SYNTHESIZER FALLBACKS ---
function _synthFallback(ac, kind) {
    const g = ac.createGain();
    g.connect(ac.destination);
    const now = ac.currentTime;

    switch (kind) {
        case 'drum': {
            // Kick Drum
            const o = ac.createOscillator();
            o.connect(g);
            o.type = 'sine';
            o.frequency.setValueAtTime(150, now);
            o.frequency.exponentialRampToValueAtTime(40, now + 0.15);
            g.gain.setValueAtTime(0.6, now);
            g.gain.exponentialRampToValueAtTime(0.001, now + 0.22);
            o.start(now);
            o.stop(now + 0.22);
            break;
        }

        case 'pop': {
            // Soft bubbly pop
            const o = ac.createOscillator();
            o.connect(g);
            o.frequency.setValueAtTime(700, now);
            o.frequency.exponentialRampToValueAtTime(1400, now + 0.08);
            g.gain.setValueAtTime(0.25, now);
            g.gain.exponentialRampToValueAtTime(0.001, now + 0.1);
            o.start(now);
            o.stop(now + 0.1);
            break;
        }

        case 'laser': {
            // Retro 8-bit laser
            const o = ac.createOscillator();
            o.connect(g);
            o.type = 'sawtooth';
            o.frequency.setValueAtTime(1200, now);
            o.frequency.exponentialRampToValueAtTime(80, now + 0.28);
            g.gain.setValueAtTime(0.2, now);
            g.gain.exponentialRampToValueAtTime(0.001, now + 0.28);
            o.start(now);
            o.stop(now + 0.28);
            break;
        }

        case 'coin': {
            // Classic Mario double-beep coin sound
            [987.77, 1318.51].forEach((f, i) => {
                const o = ac.createOscillator(), gg = ac.createGain();
                o.connect(gg);
                gg.connect(ac.destination);
                o.type = 'square';
                o.frequency.setValueAtTime(f, now + i * 0.08);
                gg.gain.setValueAtTime(0.12, now + i * 0.08);
                gg.gain.exponentialRampToValueAtTime(0.001, now + i * 0.08 + 0.18);
                o.start(now + i * 0.08);
                o.stop(now + i * 0.08 + 0.18);
            });
            break;
        }

        case 'chomp': {
            // Quick crunchy bite sequence
            [0, 0.12].forEach(t => {
                const bufferSize = ac.sampleRate * 0.06;
                const buffer = ac.createBuffer(1, bufferSize, ac.sampleRate);
                const data = buffer.getChannelData(0);
                for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;

                const src = ac.createBufferSource();
                src.buffer = buffer;
                const filter = ac.createBiquadFilter();
                filter.type = 'bandpass';
                filter.frequency.value = 800;
                filter.Q.value = 3;

                const gg = ac.createGain();
                src.connect(filter);
                filter.connect(gg);
                gg.connect(ac.destination);

                gg.gain.setValueAtTime(0.3, now + t);
                gg.gain.exponentialRampToValueAtTime(0.001, now + t + 0.06);
                src.start(now + t);
                src.stop(now + t + 0.06);
            });
            break;
        }

        case 'bark':
        case 'bark (dog)': {
            // Realistic double bark
            [0, 0.22].forEach(t => {
                const o = ac.createOscillator();
                o.type = 'triangle';
                o.connect(g);
                o.frequency.setValueAtTime(240, now + t);
                o.frequency.exponentialRampToValueAtTime(120, now + t + 0.12);
                g.gain.setValueAtTime(0.4, now + t);
                g.gain.exponentialRampToValueAtTime(0.001, now + t + 0.15);
                o.start(now + t);
                o.stop(now + t + 0.15);

                const noise = ac.createOscillator();
                noise.type = 'sawtooth';
                const noiseGain = ac.createGain();
                noise.connect(noiseGain);
                noiseGain.connect(ac.destination);
                noise.frequency.setValueAtTime(140, now + t);
                noiseGain.gain.setValueAtTime(0.15, now + t);
                noiseGain.gain.exponentialRampToValueAtTime(0.001, now + t + 0.12);
                noise.start(now + t);
                noise.stop(now + t + 0.12);
            });
            break;
        }

        case 'croak':
        case 'croak (frog)': {
            // Heavy croak sequence
            [0, 0.18, 0.36].forEach(t => {
                const o = ac.createOscillator(), gg = ac.createGain();
                o.connect(gg);
                gg.connect(ac.destination);
                o.type = 'sawtooth';
                o.frequency.setValueAtTime(90, now + t);
                o.frequency.linearRampToValueAtTime(120, now + t + 0.06);
                o.frequency.linearRampToValueAtTime(80, now + t + 0.12);
                gg.gain.setValueAtTime(0.3, now + t);
                gg.gain.exponentialRampToValueAtTime(0.001, now + t + 0.14);
                o.start(now + t);
                o.stop(now + t + 0.14);
            });
            break;
        }

        case 'meow':
        case 'meow (cat)': {
            // Classic rising meow
            const osc = ac.createOscillator();
            const filt = ac.createBiquadFilter();
            osc.type = 'sawtooth';
            osc.connect(filt);
            filt.connect(g);
            filt.type = 'bandpass';
            filt.Q.value = 5;

            osc.frequency.setValueAtTime(390, now);
            osc.frequency.linearRampToValueAtTime(800, now + 0.18);
            osc.frequency.linearRampToValueAtTime(620, now + 0.38);
            osc.frequency.linearRampToValueAtTime(450, now + 0.55);

            filt.frequency.setValueAtTime(400, now);
            filt.frequency.linearRampToValueAtTime(1500, now + 0.18);
            filt.frequency.linearRampToValueAtTime(1000, now + 0.38);
            filt.frequency.linearRampToValueAtTime(600, now + 0.55);

            g.gain.setValueAtTime(0, now);
            g.gain.linearRampToValueAtTime(0.35, now + 0.08);
            g.gain.setValueAtTime(0.35, now + 0.45);
            g.gain.exponentialRampToValueAtTime(0.001, now + 0.58);

            osc.start(now);
            osc.stop(now + 0.58);
            break;
        }

        case 'moo':
        case 'moo (cow)': {
            // Low deep cow moo
            const o1 = ac.createOscillator();
            const o2 = ac.createOscillator();
            const filter = ac.createBiquadFilter();

            o1.type = 'sawtooth';
            o2.type = 'triangle';
            o1.connect(filter);
            o2.connect(filter);
            filter.connect(g);

            filter.type = 'lowpass';
            filter.frequency.setValueAtTime(400, now);
            filter.frequency.exponentialRampToValueAtTime(150, now + 0.9);

            o1.frequency.setValueAtTime(95, now);
            o1.frequency.linearRampToValueAtTime(115, now + 0.3);
            o1.frequency.exponentialRampToValueAtTime(90, now + 0.9);

            o2.frequency.setValueAtTime(97, now);
            o2.frequency.linearRampToValueAtTime(117, now + 0.3);
            o2.frequency.exponentialRampToValueAtTime(92, now + 0.9);

            g.gain.setValueAtTime(0, now);
            g.gain.linearRampToValueAtTime(0.4, now + 0.15);
            g.gain.setValueAtTime(0.4, now + 0.6);
            g.gain.exponentialRampToValueAtTime(0.001, now + 0.95);

            o1.start(now); o2.start(now);
            o1.stop(now + 0.95); o2.stop(now + 0.95);
            break;
        }

        case 'roar':
        case 'roar (lion)': {
            // White-noise driven heavy lion growl
            const bufferSize = ac.sampleRate * 0.8;
            const buffer = ac.createBuffer(1, bufferSize, ac.sampleRate);
            const data = buffer.getChannelData(0);
            for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;

            const noise = ac.createBufferSource();
            noise.buffer = buffer;

            const lowOsc = ac.createOscillator();
            lowOsc.type = 'sawtooth';
            lowOsc.frequency.setValueAtTime(45, now);
            lowOsc.frequency.linearRampToValueAtTime(30, now + 0.8);

            const filter = ac.createBiquadFilter();
            filter.type = 'bandpass';
            filter.Q.value = 6;
            filter.frequency.setValueAtTime(250, now);
            filter.frequency.exponentialRampToValueAtTime(70, now + 0.8);

            const noiseGain = ac.createGain();
            noise.connect(filter);
            filter.connect(noiseGain);
            noiseGain.connect(g);

            const oscGain = ac.createGain();
            lowOsc.connect(oscGain);
            oscGain.connect(g);

            g.gain.setValueAtTime(0, now);
            g.gain.linearRampToValueAtTime(0.5, now + 0.1);
            g.gain.exponentialRampToValueAtTime(0.001, now + 0.8);

            noiseGain.gain.setValueAtTime(0.4, now);
            oscGain.gain.setValueAtTime(0.3, now);

            noise.start(now);
            lowOsc.start(now);
            noise.stop(now + 0.8);
            lowOsc.stop(now + 0.8);
            break;
        }

        case 'duck': {
            // Quick cartoon quack
            [0, 0.18].forEach(t => {
                const o = ac.createOscillator();
                const f = ac.createBiquadFilter();
                o.type = 'sawtooth';
                o.connect(f);
                f.connect(g);

                f.type = 'bandpass';
                f.Q.value = 9;

                o.frequency.setValueAtTime(280, now + t);
                o.frequency.linearRampToValueAtTime(380, now + t + 0.05);
                o.frequency.linearRampToValueAtTime(260, now + t + 0.12);

                f.frequency.setValueAtTime(800, now + t);
                f.frequency.linearRampToValueAtTime(1600, now + t + 0.05);
                f.frequency.linearRampToValueAtTime(700, now + t + 0.12);

                g.gain.setValueAtTime(0.3, now + t);
                g.gain.exponentialRampToValueAtTime(0.001, now + t + 0.14);

                o.start(now + t);
                o.stop(now + t + 0.14);
            });
            break;
        }

        case 'dance':
        case 'dance music': {
            // An upbeat, cute 8-bit synthetic melody
            const notes = [
                { note: 60, time: 0, dur: 0.18 }, // C4
                { note: 64, time: 0.22, dur: 0.18 }, // E4
                { note: 67, time: 0.44, dur: 0.18 }, // G4
                { note: 72, time: 0.66, dur: 0.35 }  // C5
            ];
            notes.forEach(n => {
                const o = ac.createOscillator(), gg = ac.createGain();
                o.connect(gg);
                gg.connect(ac.destination);
                o.type = 'triangle';
                o.frequency.setValueAtTime(midiToFreq(n.note), now + n.time);
                gg.gain.setValueAtTime(0.2, now + n.time);
                gg.gain.exponentialRampToValueAtTime(0.001, now + n.time + n.dur);
                o.start(now + n.time);
                o.stop(now + n.time + n.dur);
            });
            break;
        }

        case 'jungle': {
            // Atmospheric tribal tom-drum beats
            [0, 0.25, 0.5, 0.75].forEach((t, i) => {
                const o = ac.createOscillator(), gg = ac.createGain();
                o.connect(gg);
                gg.connect(ac.destination);
                o.type = 'sine';
                o.frequency.setValueAtTime(i % 2 === 0 ? 90 : 120, now + t);
                o.frequency.exponentialRampToValueAtTime(50, now + t + 0.15);
                gg.gain.setValueAtTime(0.4, now + t);
                gg.gain.exponentialRampToValueAtTime(0.001, now + t + 0.18);
                o.start(now + t);
                o.stop(now + t + 0.18);
            });
            break;
        }

        default: {
            // General beep fallback for undefined sounds
            const o = ac.createOscillator();
            o.connect(g);
            o.type = 'sine';
            o.frequency.setValueAtTime(440, now);
            g.gain.setValueAtTime(0.15, now);
            g.gain.exponentialRampToValueAtTime(0.001, now + 0.15);
            o.start(now);
            o.stop(now + 0.15);
            break;
        }
    }
}

// --- 4. EXPORTED PLAY SOUND ROUTER ---
export async function playSound(kind, projectSounds = []) {
    return new Promise(async (resolve) => {
        try {
            const sndKey = (kind || '').toLowerCase().trim();

            // ── A. Find the URL ──
            let url = null;

            // Check project uploaded sounds first
            const externalSound = projectSounds.find(s =>
                s.name?.toLowerCase() === sndKey ||
                s.id?.toLowerCase() === sndKey ||
                s.synthId?.toLowerCase() === sndKey
            );

            if (externalSound && !externalSound.synthId) {
                url = externalSound.src;
                if (!url && externalSound.md5ext) {
                    url = `https://trampoline.turbowarp.org/assets/${externalSound.md5ext}`;
                }
            }

            // Check standard CDN library
            if (!url) {
                url = CDN_ANIMAL_SOUNDS[sndKey];
            }

            // ── B. Attempt HTML5 Audio Player ──
            if (url) {
                const cleanUrl = getCleanAssetUrl(url);
                const audio = new Audio(cleanUrl);
                audio.crossOrigin = 'anonymous';

                let played = false;

                const playPromise = new Promise((resPlay) => {
                    audio.addEventListener('canplaythrough', () => {
                        audio.play()
                            .then(() => {
                                played = true;
                                resPlay(true);
                            })
                            .catch(() => {
                                resPlay(false);
                            });
                    }, { once: true });

                    audio.onerror = () => resPlay(false);

                    // 1.5s load safety timeout
                    setTimeout(() => {
                        if (!played) resPlay(false);
                    }, 1500);
                });

                const success = await playPromise;
                if (success) {
                    audio.onended = () => resolve(audio.duration * 1000);
                    return;
                }
            }

            // ── C. High Fidelity Synthesizer Fallback ──
            const ac = getAudioContext();
            if (ac) {
                _synthFallback(ac, sndKey);
            }

            // Standard durations for wait-block scheduling
            const durations = {
                chomp: 250, pop: 100, laser: 280, coin: 400,
                dance: 1100, 'dance music': 1100, drum: 220,
                jungle: 1000, meow: 580, 'meow (cat)': 580,
                bark: 300, 'bark (dog)': 300, croak: 500,
                'croak (frog)': 500, moo: 950, 'moo (cow)': 950,
                roar: 800, 'roar (lion)': 800, duck: 300
            };

            const duration = durations[sndKey] || 300;
            setTimeout(() => resolve(duration), duration);

        } catch (e) {
            resolve(300);
        }
    });
}
