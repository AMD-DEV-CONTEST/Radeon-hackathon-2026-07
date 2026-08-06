(
var outputPath = (thisProcess.nowExecutingPath.dirname +/+ "audio/frontier-gtm-score-48k24.wav").standardizePath;
var options = ServerOptions.new;
var defs;
var events;
var score;

options.numOutputBusChannels = 2;
options.numInputBusChannels = 0;
options.sampleRate = 48000;
options.blockSize = 64;
options.memSize = 65536;

defs = [
    SynthDef(\frontierPad, { |out=0, freq=82, amp=0.12, dur=8, pan=0|
        var env = EnvGen.kr(Env.linen(1.4, max(0.2, dur - 2.8), 1.4, curve: [-4, -2]), doneAction: 2);
        var tone = Mix.ar(SinOsc.ar([freq, freq * 1.501, freq * 2.006], [0, 0.2, 0.5], [0.72, 0.22, 0.11]));
        var air = BPF.ar(PinkNoise.ar(0.13), freq * 8, 0.25);
        var signal = LPF.ar(tone + air, 4100);
        signal = FreeVerb.ar(signal, 0.36, 0.78, 0.26);
        Out.ar(out, Pan2.ar(signal, pan, amp) * env);
    }),
    SynthDef(\frontierImpact, { |out=0, freq=52, amp=0.34, dur=1.2, pan=0|
        var env = EnvGen.kr(Env.perc(0.004, dur, curve: -6), doneAction: 2);
        var body = SinOsc.ar(XLine.kr(freq * 2.4, freq, dur), 0, 0.82);
        var crack = HPF.ar(WhiteNoise.ar(0.32), 1800) * EnvGen.kr(Env.perc(0.001, 0.09));
        Out.ar(out, Pan2.ar((body + crack) * env, pan, amp));
    }),
    SynthDef(\frontierTick, { |out=0, freq=2100, amp=0.1, pan=0|
        var env = EnvGen.kr(Env.perc(0.001, 0.12, curve: -9), doneAction: 2);
        var signal = SinOsc.ar(freq, 0, 0.64) + HPF.ar(WhiteNoise.ar(0.14), 5000);
        Out.ar(out, Pan2.ar(signal * env, pan, amp));
    }),
    SynthDef(\frontierRise, { |out=0, amp=0.14, dur=2.2, pan=0|
        var env = EnvGen.kr(Env.linen(0.05, dur - 0.1, 0.05, curve: 3), doneAction: 2);
        var center = XLine.kr(280, 7600, dur);
        var signal = BPF.ar(PinkNoise.ar(0.7), center, 0.12) + SinOsc.ar(center * 0.38, 0, 0.08);
        Out.ar(out, Pan2.ar(signal * env, pan, amp));
    }),
    SynthDef(\frontierPulse, { |out=0, freq=118, amp=0.11, dur=0.42, pan=0|
        var env = EnvGen.kr(Env.perc(0.006, dur, curve: -5), doneAction: 2);
        var signal = LPF.ar(Saw.ar(freq * [1, 1.006], 0.35).sum, 1300);
        Out.ar(out, Pan2.ar(signal * env, pan, amp));
    })
];

events = defs.collect { |definition| [0.0, [\d_recv, definition.asBytes]] };

events = events ++ [
    [0.02, [\s_new, \frontierPad, 1000, 0, 0, \freq, 55, \amp, 0.13, \dur, 12.0, \pan, -0.12]],
    [0.03, [\s_new, \frontierImpact, 1001, 0, 0, \freq, 43, \amp, 0.44, \dur, 1.7]],
    [1.35, [\s_new, \frontierTick, 1002, 0, 0, \freq, 2400, \amp, 0.09, \pan, -0.55]],
    [2.35, [\s_new, \frontierTick, 1003, 0, 0, \freq, 3100, \amp, 0.07, \pan, 0.48]],
    [3.40, [\s_new, \frontierRise, 1004, 0, 0, \amp, 0.12, \dur, 1.5]],
    [4.62, [\s_new, \frontierImpact, 1005, 0, 0, \freq, 62, \amp, 0.30, \dur, 0.95]],
    [4.70, [\s_new, \frontierPad, 1006, 0, 0, \freq, 73, \amp, 0.11, \dur, 9.0, \pan, 0.1]],
    [6.25, [\s_new, \frontierPulse, 1007, 0, 0, \freq, 146, \amp, 0.11, \pan, -0.42]],
    [7.05, [\s_new, \frontierPulse, 1008, 0, 0, \freq, 164, \amp, 0.10, \pan, 0.42]],
    [7.85, [\s_new, \frontierPulse, 1009, 0, 0, \freq, 182, \amp, 0.10, \pan, -0.2]],
    [9.50, [\s_new, \frontierRise, 1010, 0, 0, \amp, 0.10, \dur, 1.9]],
    [11.18, [\s_new, \frontierImpact, 1011, 0, 0, \freq, 48, \amp, 0.38, \dur, 1.25]],
    [11.24, [\s_new, \frontierPad, 1012, 0, 0, \freq, 92, \amp, 0.105, \dur, 13.0, \pan, -0.08]],
    [12.10, [\s_new, \frontierTick, 1013, 0, 0, \freq, 1850, \amp, 0.10, \pan, -0.65]],
    [15.05, [\s_new, \frontierImpact, 1014, 0, 0, \freq, 68, \amp, 0.27, \dur, 0.8, \pan, -0.3]],
    [15.55, [\s_new, \frontierTick, 1015, 0, 0, \freq, 2250, \amp, 0.08, \pan, -0.55]],
    [18.90, [\s_new, \frontierImpact, 1016, 0, 0, \freq, 72, \amp, 0.26, \dur, 0.75, \pan, 0.28]],
    [19.35, [\s_new, \frontierTick, 1017, 0, 0, \freq, 2700, \amp, 0.08, \pan, 0.55]],
    [22.30, [\s_new, \frontierRise, 1018, 0, 0, \amp, 0.12, \dur, 1.4]],
    [23.22, [\s_new, \frontierImpact, 1019, 0, 0, \freq, 46, \amp, 0.38, \dur, 1.4]],
    [23.26, [\s_new, \frontierPad, 1020, 0, 0, \freq, 61, \amp, 0.12, \dur, 10.5, \pan, 0.12]],
    [24.10, [\s_new, \frontierPulse, 1021, 0, 0, \freq, 128, \amp, 0.11, \pan, -0.4]],
    [25.10, [\s_new, \frontierPulse, 1022, 0, 0, \freq, 144, \amp, 0.10, \pan, 0.4]],
    [26.10, [\s_new, \frontierPulse, 1023, 0, 0, \freq, 161, \amp, 0.10, \pan, -0.25]],
    [29.20, [\s_new, \frontierRise, 1024, 0, 0, \amp, 0.115, \dur, 2.2]],
    [31.22, [\s_new, \frontierImpact, 1025, 0, 0, \freq, 41, \amp, 0.46, \dur, 1.7]],
    [31.28, [\s_new, \frontierPad, 1026, 0, 0, \freq, 49, \amp, 0.13, \dur, 7.2]],
    [33.10, [\s_new, \frontierTick, 1027, 0, 0, \freq, 1950, \amp, 0.095, \pan, -0.5]],
    [34.05, [\s_new, \frontierTick, 1028, 0, 0, \freq, 2450, \amp, 0.085, \pan, 0.5]],
    [36.30, [\s_new, \frontierRise, 1029, 0, 0, \amp, 0.10, \dur, 1.4]],
    [37.40, [\s_new, \frontierImpact, 1030, 0, 0, \freq, 36, \amp, 0.36, \dur, 1.0]],
    [38.40, [\c_set, 0, 0]]
];

score = Score(events.sort({ |a, b| a[0] < b[0] }));
score.recordNRT(
    outputFilePath: outputPath,
    headerFormat: "WAV",
    sampleFormat: "int24",
    options: options,
    duration: 38.5,
    action: { "FRONTIER_SCORE_COMPLETE".postln; 0.exit; }
);
)
