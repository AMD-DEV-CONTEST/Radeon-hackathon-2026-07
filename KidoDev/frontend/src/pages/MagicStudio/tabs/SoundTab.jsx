import React from 'react';
import { playSound } from '../soundEngine';

export function SoundTab({ sp, projectSoundsRef, _force, addLog, setLibMode }) {
    const sprite = sp.current;
    const sounds = projectSoundsRef.current;

    const [selectedSound, setSelectedSound] = React.useState(null);
    const [isRecording, setIsRecording] = React.useState(false);
    const mediaRecorderRef = React.useRef(null);
    const audioChunksRef = React.useRef([]);

    const startRecording = async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const recorder = new MediaRecorder(stream);
            mediaRecorderRef.current = recorder;
            recorder.ondataavailable = e => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
            recorder.onstop = () => {
                const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
                const url = URL.createObjectURL(blob);
                const newSound = { id: 'snd_' + Date.now(), name: 'recording1', src: url };
                projectSoundsRef.current.push(newSound);
                audioChunksRef.current = [];
                _force(x => x + 1);
            };
            audioChunksRef.current = [];
            recorder.start();
            setIsRecording(true);
        } catch (err) {
            console.error('Mic error:', err);
            alert('Microphone access denied or unavailable.');
        }
    };

    const stopRecording = () => {
        if (mediaRecorderRef.current && isRecording) {
            mediaRecorderRef.current.stop();
            mediaRecorderRef.current.stream.getTracks().forEach(t => t.stop());
            setIsRecording(false);
        }
    };

    const applyEffect = async (effectType) => {
        if (!selectedSound || !selectedSound.src) return;
        try {
            const actx = new (window.AudioContext || window.webkitAudioContext)();
            const response = await fetch(selectedSound.src);
            const arrayBuffer = await response.arrayBuffer();
            const audioBuffer = await actx.decodeAudioData(arrayBuffer);

            let offlineCtx;
            let finalBuffer;

            if (effectType === 'reverse') {
                for (let i = 0; i < audioBuffer.numberOfChannels; i++) {
                    Array.prototype.reverse.call(audioBuffer.getChannelData(i));
                }
                finalBuffer = audioBuffer;
            } else if (effectType === 'faster' || effectType === 'slower') {
                const rate = effectType === 'faster' ? 1.5 : 0.75;
                const newLen = audioBuffer.length / rate;
                offlineCtx = new OfflineAudioContext(audioBuffer.numberOfChannels, newLen, audioBuffer.sampleRate);
                const source = offlineCtx.createBufferSource();
                source.buffer = audioBuffer;
                source.playbackRate.value = rate;
                source.connect(offlineCtx.destination);
                source.start();
                finalBuffer = await offlineCtx.startRendering();
            } else if (effectType === 'louder' || effectType === 'softer') {
                const gain = effectType === 'louder' ? 1.5 : 0.5;
                offlineCtx = new OfflineAudioContext(audioBuffer.numberOfChannels, audioBuffer.length, audioBuffer.sampleRate);
                const source = offlineCtx.createBufferSource();
                const gainNode = offlineCtx.createGain();
                source.buffer = audioBuffer;
                gainNode.gain.value = gain;
                source.connect(gainNode);
                gainNode.connect(offlineCtx.destination);
                source.start();
                finalBuffer = await offlineCtx.startRendering();
            }

            if (finalBuffer) {
                const wavBlob = bufferToWave(finalBuffer, finalBuffer.length);
                selectedSound.src = URL.createObjectURL(wavBlob);
                _force(x => x + 1);
            }
        } catch (e) { console.error('Audio effect failed', e); }
    };

    function bufferToWave(abuffer, len) {
        let numOfChan = abuffer.numberOfChannels, length = len * numOfChan * 2 + 44, buffer = new ArrayBuffer(length), view = new DataView(buffer), channels = [], i, sample, offset = 0, pos = 0;
        const setUint16 = data => { view.setUint16(pos, data, true); pos += 2; };
        const setUint32 = data => { view.setUint32(pos, data, true); pos += 4; };
        setUint32(0x46464952); setUint32(length - 8); setUint32(0x45564157); setUint32(0x20746d66); setUint32(16); setUint16(1); setUint16(numOfChan); setUint32(abuffer.sampleRate); setUint32(abuffer.sampleRate * 2 * numOfChan); setUint16(numOfChan * 2); setUint16(16); setUint32(0x61746164); setUint32(length - pos - 4);
        for (i = 0; i < abuffer.numberOfChannels; i++) channels.push(abuffer.getChannelData(i));
        while (pos < length) {
            for (i = 0; i < numOfChan; i++) {
                sample = Math.max(-1, Math.min(1, channels[i][offset]));
                sample = (0.5 + sample < 0 ? sample * 32768 : sample * 32767) | 0;
                view.setInt16(pos, sample, true); pos += 2;
            }
            offset++
        }
        return new Blob([buffer], { type: "audio/wav" });
    }

    return (
        <div style={{ flex: 1, display: 'flex', background: '#1E3A5F', color: '#fff' }}>
            <div style={{ width: 150, background: '#162d4a', borderRight: '1px solid #2D5A8E', display: 'flex', flexDirection: 'column', padding: '10px 5px', gap: 8 }}>

                <div style={{ display: 'flex', gap: 5, padding: '0 5px' }}>
                    <button onClick={isRecording ? stopRecording : startRecording} style={{ flex: 1, background: isRecording ? '#EF4444' : '#14B8A6', color: '#fff', border: 'none', borderRadius: 8, padding: '8px 0', fontSize: 12, fontWeight: 800, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                        <span style={{ fontSize: 16 }}>{isRecording ? '⏹' : '🎤'}</span> {isRecording ? 'Stop' : 'Record'}
                    </button>
                    <button title="Library" onClick={() => { if (setLibMode) setLibMode('sound'); }} style={{ width: 32, background: 'linear-gradient(135deg, #6366F1, #4F46E5)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 16, fontWeight: 900, cursor: 'pointer' }}>+</button>
                </div>

                <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4, marginTop: 5 }}>
                    {sounds.length === 0 && (
                        <div style={{ fontSize: 11, color: '#64748B', textAlign: 'center', padding: '20px 0' }}>No Sounds Added</div>
                    )}
                    {sounds.map((s, i) => (
                        <div
                            key={s.id}
                            onClick={() => setSelectedSound(s)}
                            style={{
                                display: 'flex', alignItems: 'center', gap: 10, padding: '10px 8px',
                                background: selectedSound?.id === s.id ? '#4F46E5' : 'rgba(255,255,255,0.05)', borderRadius: 8, cursor: 'pointer',
                                border: selectedSound?.id === s.id ? '2px solid #818CF8' : '2px solid transparent'
                            }}
                        >
                            <div style={{ fontSize: 10, fontWeight: 700, color: '#CBD5E1', width: 15 }}>{i + 1}</div>
                            <button onClick={(e) => { 
                                e.stopPropagation(); 
                                const hardcodedSounds = {
                                    'meow': 'Cat.mp3',
                                    'meow2': 'Cat2.mp3',
                                    'bark': 'Dog1.mp3',
                                    'croak': 'Frog.mp3',
                                    'moo': 'Cow.mp3',
                                    'roar': 'Lion.mp3'
                                };
                                const sndKey = (s.name || '').toLowerCase().trim();
                                let url = null;
                                if (hardcodedSounds[sndKey]) {
                                    url = `https://raw.githubusercontent.com/scratchfoundation/scratch-audio/develop/src/soundbank/${hardcodedSounds[sndKey]}`;
                                } else if (s.src) {
                                    url = s.src;
                                } else if (s.md5ext) {
                                    url = `https://trampoline.turbowarp.org/assets/${s.md5ext}`;
                                }
                                
                                if (url) {
                                    new Audio(url).play().catch(() => {});
                                } else {
                                    playSound(s.synthId || s.id, projectSoundsRef.current); 
                                }
                            }} style={{ background: '#312E81', color: '#fff', border: 'none', borderRadius: '50%', width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', flexShrink: 0 }}>
                                ▶
                            </button>
                            <div style={{ fontSize: 11, fontWeight: 700, color: '#fff', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</div>
                        </div>
                    ))}
                </div>
            </div>

            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 20, position: 'relative', background: '#0F172A' }}>
                {selectedSound ? (
                    <>
                        <div style={{ position: 'absolute', top: 15, left: 15, background: 'rgba(0,0,0,0.5)', padding: '6px 16px', borderRadius: 12, fontSize: 16, fontWeight: 800, color: '#fff' }}>
                            {selectedSound.name}
                        </div>

                        <div style={{ width: '80%', height: 180, background: 'linear-gradient(180deg, rgba(99,102,241,0.1) 0%, rgba(99,102,241,0.3) 100%)', borderRadius: 16, border: '2px solid #4F46E5', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', position: 'relative' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 4, height: '100%' }}>
                                {Array.from({ length: 40 }).map((_, i) => (
                                    <div key={i} style={{ width: 6, height: Math.max(10, Math.random() * 140), background: '#818CF8', borderRadius: 4, opacity: 0.8 }}></div>
                                ))}
                            </div>
                        </div>

                        <div style={{ display: 'flex', gap: 15, marginTop: 30, background: '#1E293B', padding: '15px 25px', borderRadius: 16, boxShadow: '0 10px 30px rgba(0,0,0,0.5)' }}>
                            <EffectBtn icon="🐇" label="Faster" onClick={() => applyEffect('faster')} />
                            <EffectBtn icon="🐢" label="Slower" onClick={() => applyEffect('slower')} />
                            <div style={{ width: 2, background: '#334155' }} />
                            <EffectBtn icon="🔊" label="Louder" onClick={() => applyEffect('louder')} />
                            <EffectBtn icon="🔉" label="Softer" onClick={() => applyEffect('softer')} />
                            <div style={{ width: 2, background: '#334155' }} />
                            <EffectBtn icon="🔄" label="Reverse" onClick={() => applyEffect('reverse')} />
                        </div>
                    </>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', opacity: 0.5 }}>
                        <div style={{ fontSize: 80, marginBottom: 20 }}>🎧</div>
                        <div style={{ fontSize: 16, fontWeight: 700, color: '#94A3B8' }}>Select or Record a sound to edit</div>
                    </div>
                )}
            </div>
        </div>
    );
}

function EffectBtn({ icon, label, onClick }) {
    return (
        <button onClick={onClick} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, background: '#334155', border: 'none', borderRadius: 12, padding: '10px 15px', cursor: 'pointer', transition: '0.2s' }}>
            <span style={{ fontSize: 24 }}>{icon}</span>
            <span style={{ fontSize: 11, fontWeight: 800, color: '#CBD5E1' }}>{label}</span>
        </button>
    );
}
