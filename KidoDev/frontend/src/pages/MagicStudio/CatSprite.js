export const STYLE_ID = 'kido-cat-agent-v10-video';

export const CAT_COLORS = {
    Motion: '#4C97FF', Looks: '#9966FF', Sound: '#CF63CF',
    Events: '#FFAB19', Control: '#FFAB19', Sensing: '#5CB1D6',
    Operators: '#59C059', Variables: '#FF8C1A', 'My Blocks': '#FF6680',
};
export const catColor = cat => CAT_COLORS[cat] || '#4C97FF';

/* ───────────────────────────────────────────────────────────────
   VIDEO CLIP CONFIG
   ─────────────────────────────────────────────────────────────── */
const VIDEO_BASE = '/assets/videos/';

const STATE_FILES = {
    idle: 'cat_idle.webm',
    run: 'cat_run.webm',
    grab: 'cat_grab.webm',
    drag: 'cat_drag.webm',
    cheer: 'cat_cheer.webm',
};

// States that should loop continuously while active vs. play once.
const LOOPING_STATES = new Set(['idle', 'run', 'drag']);

// Native pixel size of the cropped/keyed clips (must match the
// ffmpeg crop used to produce them: crop=536:480:130:0).
const CLIP_W = 536, CLIP_H = 480;

// On-screen display size of the sprite box. Keeps the clip's
// aspect ratio so the cat isn't stretched.
const DISPLAY_W = 168;
const DISPLAY_H = Math.round(DISPLAY_W * CLIP_H / CLIP_W); // ≈ 150

/* ───────────────────────────────────────────────────────────────
   PAW CALIBRATION — tune these two numbers to match your clips.
   Both are OFFSETS FROM THE SPRITE BOX CENTER, in pixels, describing
   where the cat's front paw actually sits inside the video frame.
   ─────────────────────────────────────────────────────────────── */
// Positive = paw sits to the LEFT of box center (cat faces left).
// Increase this if there's still a gap between the paw and the block
// during grab; decrease if the paw overlaps too far into the block.
const PAW_OFFSET_X = DISPLAY_W * 0.50;

// Positive = paw sits BELOW box center. Negative = paw sits ABOVE box
// center. If the cat currently appears above the block, increase this
// value (try steps of 10–20) until the paw lines up with the block's
// vertical middle.
const PAW_OFFSET_Y = -20;

// Fixed pixel gap kept between the block's edge and the cat's paw when
// idle/cheering beside a placed block. Lower = tighter to the block.
const BODY_SIDE_GAP = 8;

/* ───────────────────────────────────────────────────────────────
   STYLES
   ─────────────────────────────────────────────────────────────── */
export function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const el = document.createElement('style');
    el.id = STYLE_ID;
    el.textContent = `
    /* ═══ SPRITE CONTAINER ═══ */
    .ksa-sprite {
        position: fixed; z-index: 999999;
        width: ${DISPLAY_W}px; height: ${DISPLAY_H}px;
        pointer-events: none; user-select: none;
        filter: drop-shadow(0 4px 10px rgba(0,0,0,.32));
        will-change: left, top;
    }
    .ksa-cat-video {
        position: absolute; top: 0; left: 0;
        width: 100%; height: 100%;
        object-fit: contain;
        pointer-events: none;
    }

    /* ═══ GHOST BLOCK ═══ */
    .ksa-ghost {
        position: fixed; z-index: 999997; pointer-events: none;
        padding: 5px 13px 5px 10px; border-radius: 6px;
        font-size: 13px; font-weight: 700;
        font-family: 'Fredoka','Outfit',sans-serif; color: #fff;
        border-top:    3px solid rgba(255,255,255,.55);
        border-left:   3px solid rgba(255,255,255,.35);
        border-bottom: 3px solid rgba(0,0,0,.28);
        border-right:  3px solid rgba(0,0,0,.22);
        box-shadow: 0 7px 24px rgba(0,0,0,.46), 0 2px 6px rgba(0,0,0,.3),
                    inset 0 1px 0 rgba(255,255,255,.28);
        white-space: nowrap; opacity: 0;
        will-change: left, top;
    }
    .ksa-ghost.on {
        opacity: 1;
        animation: ksaGhostPop .22s cubic-bezier(.34,1.56,.64,1) forwards;
    }
    @keyframes ksaGhostPop {
        from{transform:scale(.4);opacity:0}
        to  {transform:scale(1);opacity:1}
    }

    /* ═══ SNAP TARGET ═══ */
    .ksa-snap {
        position: fixed; pointer-events: none; z-index: 999996;
        border: 3px dashed #22c55e; border-radius: 7px;
        background: rgba(34,197,94,.06);
        box-shadow: 0 0 16px rgba(34,197,94,.7);
        animation: ksaSnapPulse .5s ease-in-out infinite alternate;
    }
    @keyframes ksaSnapPulse{from{opacity:.38}to{opacity:1}}

    /* ═══ SPARKLES (optional flourish) ═══ */
    .ksa-sparkle {
        position: fixed; z-index: 999998; pointer-events: none;
        font-size: 20px;
        animation: ksaSparkleFly .9s ease-out forwards;
    }
    @keyframes ksaSparkleFly {
        from { transform: translate(0,0) scale(1); opacity: 1; }
        to   { transform: translate(var(--dx), var(--dy)) scale(.3); opacity: 0; }
    }
    `;
    document.head.appendChild(el);
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

/* ───────────────────────────────────────────────────────────────
   SPARKLES (unchanged flourish helper, unused by default flow)
   ─────────────────────────────────────────────────────────────── */
export function sparkles(x, y) {
    ['✨', '⭐', '🌟', '💫', '🎉', '🔥'].forEach((em, i) => {
        const el = document.createElement('div');
        el.className = 'ksa-sparkle'; el.textContent = em;
        const a = Math.PI * 2 * i / 6 + Math.random() * .5, d = 38 + Math.random() * 48;
        Object.assign(el.style, { left: (x - 10) + 'px', top: (y - 10) + 'px' });
        el.style.setProperty('--dx', Math.round(Math.cos(a) * d) + 'px');
        el.style.setProperty('--dy', Math.round(Math.sin(a) * d) + 'px');
        el.style.animationDelay = (Math.random() * .1) + 's';
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 920);
    });
}

/* ───────────────────────────────────────────────────────────────
   CAT SPRITE
   ─────────────────────────────────────────────────────────────── */
export class CatSprite {
    /**
     * @param {{left:number, right:number, top:number, bottom:number}} bounds
     *        Screen-space rect the cat should stay clamped inside
     *        (typically the Blockly editor's bounding rect).
     */
    constructor(bounds) {
        this.bounds = bounds || null;
        this.containerEl = null;
        this.videos = {};
        this.activeState = null;
        this.ghostEl = null;
        this.snapEl = null;
        injectStyles();
    }

    /* ── lifecycle ── */

    createSprite() {
        this.containerEl = document.createElement('div');
        this.containerEl.className = 'ksa-sprite';
        Object.assign(this.containerEl.style, { left: '-300px', top: '-300px' });

        for (const [state, file] of Object.entries(STATE_FILES)) {
            const v = document.createElement('video');
            v.src = VIDEO_BASE + file;
            v.className = 'ksa-cat-video';
            v.muted = true;
            v.playsInline = true;
            v.preload = 'auto';
            v.loop = LOOPING_STATES.has(state);
            v.style.display = 'none';
            // Autoplay can be blocked before user interaction; play() is
            // re-invoked explicitly in setState/playOnce as a fallback.
            this.containerEl.appendChild(v);
            this.videos[state] = v;
        }

        document.body.appendChild(this.containerEl);
        return this.containerEl;
    }

    createGhost(label, category) {
        this.ghostEl = document.createElement('div');
        this.ghostEl.className = 'ksa-ghost';
        this.ghostEl.textContent = label;
        this.ghostEl.style.background = catColor(category);
        document.body.appendChild(this.ghostEl);
        return this.ghostEl;
    }

    /**
     * Switch which clip is showing. Looping states (idle/run/drag) just
     * keep playing; one-shot states (grab/cheer) restart from frame 0
     * every time setState is called for them.
     */
    setState(state) {
        const v = this.videos[state];
        if (!this.containerEl || !v) return;

        if (this.activeState === state) {
            if (!LOOPING_STATES.has(state)) {
                v.currentTime = 0;
                v.play().catch(() => { });
            }
            return;
        }

        for (const [s, ov] of Object.entries(this.videos)) {
            if (s !== state) { ov.pause(); ov.style.display = 'none'; }
        }

        v.style.display = 'block';
        v.currentTime = 0;
        v.play().catch(() => { });
        this.activeState = state;
    }

    /**
     * Play a one-shot (non-looping) clip and resolve once it actually
     * finishes (falls back to a timeout in case 'ended' never fires,
     * e.g. autoplay got blocked).
     */
    playOnce(state, timeoutMs = 2500) {
        this.setState(state);
        const v = this.videos[state];
        if (!v) return sleep(0);
        return new Promise(resolve => {
            let done = false;
            const finish = () => {
                if (done) return;
                done = true;
                v.removeEventListener('ended', finish);
                resolve();
            };
            v.addEventListener('ended', finish, { once: true });
            setTimeout(finish, timeoutMs);
        });
    }

    setBounds(bounds) { this.bounds = bounds; }

    /* ── positioning ── */

    _clamp(x, y) {
        const r = this.bounds;
        if (!r) return { x, y };
        return {
            x: Math.max(r.left + DISPLAY_W / 2, Math.min(x, r.right - DISPLAY_W / 2)),
            y: Math.max(r.top + DISPLAY_H / 2, Math.min(y, r.bottom - DISPLAY_H / 2)),
        };
    }

    /**
     * Places the sprite box CENTERED on (x, y). This is the single
     * source of truth for the box-center↔screen-point mapping — every
     * other placement helper computes a center point and forwards here.
     */
    place(x, y) {
        if (!this.containerEl) return;
        const c = this._clamp(x, y);
        this.containerEl.style.left = (c.x - DISPLAY_W / 2) + 'px';
        this.containerEl.style.top = (c.y - DISPLAY_H / 2) + 'px';
    }

    /**
     * (px, py) is the desired screen position of the cat's PAW, not the
     * sprite box center. This is what "grab"/"drag"/"cheer" should use
     * so the paw actually touches the block instead of leaving a gap.
     * Both PAW_OFFSET_X and PAW_OFFSET_Y are applied here.
     */
    placeByPaw(px, py) {
        this.place(px + PAW_OFFSET_X, py + PAW_OFFSET_Y);
    }

    /**
     * Same anchor math as placeByPaw — kept as a distinct method name
     * for readability at call sites (drag / cheer beside a block), but
     * intentionally identical so the paw target is computed exactly one
     * way everywhere.
     */
    placeByPawRightOf(px, py) {
        this.place(px + PAW_OFFSET_X, py + PAW_OFFSET_Y);
    }

    /**
     * Anchor the sprite beside a concrete block's on-screen rect
     * (post-drop, post-layout) — used right before cheer() so the cat
     * sits tightly next to the ACTUAL placed block.
     * @param {{left:number, top:number, width:number, height:number}} rect
     */
    anchorToBlockRect(rect) {
        if (!rect) return;
        const px = rect.left - BODY_SIDE_GAP;
        const py = rect.top + rect.height / 2;
        this.placeByPaw(px, py);
    }

    placeGhost(x, y) {
        if (!this.ghostEl) return;
        this.ghostEl.style.left = x + 'px';
        this.ghostEl.style.top = y + 'px';
    }

    teleport(x, y) {
        if (!this.containerEl) return;
        this.containerEl.style.transition = 'none';
        this.place(x, y);
        requestAnimationFrame(() => { if (this.containerEl) this.containerEl.style.transition = ''; });
    }

    showGhost() { this.ghostEl?.classList.add('on'); }
    hideGhost() {
        if (!this.ghostEl) return;
        this.ghostEl.classList.remove('on');
        this.ghostEl.style.opacity = '0';
    }

    showSnapTarget(rect) {
        this.removeSnapTarget();
        if (!rect) return;
        this.snapEl = document.createElement('div');
        this.snapEl.className = 'ksa-snap';
        Object.assign(this.snapEl.style, {
            left: (rect.left - 3) + 'px', top: (rect.top - 3) + 'px',
            width: (rect.width + 6) + 'px', height: (rect.height + 6) + 'px',
        });
        document.body.appendChild(this.snapEl);
    }

    removeSnapTarget() { this.snapEl?.remove(); this.snapEl = null; }

    /**
     * @param {boolean} byPaw  When true, x0/y0/x1/y1 are PAW target
     *        positions (used for the run-up to a block) rather than
     *        sprite-box-center positions.
     */
    animateTo(x0, y0, x1, y1, steps, frameMs, isDeadFn, byPaw = false) {
        const setPos = byPaw ? (x, y) => this.placeByPaw(x, y) : (x, y) => this.place(x, y);
        return new Promise(res => {
            let i = 0;
            const tick = async () => {
                if (isDeadFn?.()) return res();
                i++;
                setPos(x0 + (x1 - x0) * ease(i / steps), y0 + (y1 - y0) * ease(i / steps));
                if (i >= steps) return res();
                await sleep(frameMs); tick();
            };
            tick();
        });
    }

    /**
     * Drags the ghost block from (x0,y0) to (x1,y1). These coordinates
     * are the PAW/block position (not sprite-box center) so the cat's
     * hand realistically stays on the block the whole way.
     *
     * The ghost block and the cat's paw share the EXACT same computed
     * (cx, cy) anchor point every frame so the block moves rigidly WITH
     * the hand instead of trailing it. The idle bob tapers to zero by
     * the final frame so the paw lands EXACTLY on (x1, y1).
     */
    animateDrag(x0, y0, x1, y1, steps, frameMs, isDeadFn) {
        return new Promise(res => {
            let i = 0;
            const tick = async () => {
                if (isDeadFn?.()) return res();
                i++;
                const e = ease(i / steps);
                const bobEnvelope = 1 - ease(i / steps); // decays to 0 by the last frame
                const cx = x0 + (x1 - x0) * e;
                const cy = y0 + (y1 - y0) * e + Math.sin(i * 0.58) * 3 * bobEnvelope;

                // Paw and ghost locked to the identical anchor point —
                // the block moves rigidly WITH the hand, not near it.
                this.placeByPawRightOf(cx, cy);
                this.placeGhost(cx - 6, cy - 8);

                if (i >= steps) return res();
                await sleep(frameMs); tick();
            };
            tick();
        });
    }

    /* ── teardown ── */

    destroy() {
        for (const v of Object.values(this.videos)) {
            try { v.pause(); v.removeAttribute('src'); v.load(); } catch (_) { }
        }
        this.videos = {};
        [this.containerEl, this.ghostEl, this.snapEl].forEach(e => e?.remove());
        this.containerEl = this.ghostEl = this.snapEl = null;
        this.activeState = null;
    }
}