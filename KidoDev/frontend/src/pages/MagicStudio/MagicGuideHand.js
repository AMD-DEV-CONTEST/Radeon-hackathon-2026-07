import * as Blockly from "blockly";
const handPointerUrl = "/assets/Handpointer1.png";

let activeHand = null;
const STYLE_ID = "kido-magic-hand-styles";

/* ─────────────────────────────
   STYLE
───────────────────────────── */

function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;

    style.textContent = `
    .kido-hand {
        position: fixed;
        z-index: 999999;
        width: 48px;
        height: 48px;
        pointer-events: none;
        user-select: none;
        background-image: url('${handPointerUrl}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        filter: drop-shadow(0 4px 8px rgba(0,0,0,0.35));
        animation: handBounce 0.9s ease-in-out infinite;
        transition: left 0.45s cubic-bezier(0.34,1.56,0.64,1),
                    top 0.45s cubic-bezier(0.34,1.56,0.64,1);
    }

    /* Bounce purely in X — nudges toward the block */
    @keyframes handBounce {
        0%   { transform: translateX(0px);   }
        50%  { transform: translateX(8px);   }
        100% { transform: translateX(0px);   }
    }

    .kido-ring {
        position: fixed;
        width: 30px;
        height: 30px;
        border: 3px solid #22c55e;
        border-radius: 50%;
        transform: translate(-50%, -50%);
        animation: ring 1s infinite;
        z-index: 999998;
        pointer-events: none;
    }

    @keyframes ring {
        0% { width: 20px; height: 20px; opacity: 0.9; }
        100% { width: 60px; height: 60px; opacity: 0; }
    }
    `;

    document.head.appendChild(style);
}

/* ─────────────────────────────
   HELPERS
───────────────────────────── */

function center(el) {
    const r = el.getBoundingClientRect();
    return {
        x: r.left + r.width / 2,
        y: r.top + r.height / 2
    };
}

/* ─────────────────────────────
   MAIN CLASS
───────────────────────────── */

class MagicHand {
    constructor(ws, block) {
        this.ws = ws;
        this.block = block;
        this.hand = null;
        this.ring = null;
        this.dead = false;

        injectStyles();
    }

    start() {
        this.createHand();
        this.goCategory();
        this.watch();
    }

    createHand() {
        this.hand = document.createElement("div");
        this.hand.className = "kido-hand";
        this.hand.setAttribute("data-label", this.block.label);

        document.body.appendChild(this.hand);
    }

    /*
     * Place the hand so the finger tip points AT (x, y).
     * The SVG finger tip is at the right edge after scaleX(-1),
     * so we offset left by the full hand width so the tip lands on the target.
     * We also add a small gap (GAP) so the hand sits beside the block, not on it.
     */
    place(x, y) {
        if (!this.hand) return;

        const W = 48;   // hand width
        const GAP = 6;  // pixel gap between finger tip and block edge

        // Position hand so its right edge (the finger tip) is GAP pixels left of x
        this.hand.style.left = (x - W - GAP) + "px";
        // Center vertically on y
        this.hand.style.top = (y - W / 2) + "px";
    }

    /* ─────────────────────────────
       CATEGORY (FIXED RETRY LOOP)
    ───────────────────────────── */

    goCategory() {
        if (this.dead) return;

        const tryFind = () => {
            const toolbox = this.ws.getToolbox?.();
            const items = toolbox?.getToolboxItems?.() || [];

            for (const item of items) {
                const name = item.getName?.();
                if (name === this.block.category) {
                    toolbox.setSelectedItem(item);

                    setTimeout(() => this.goFlyout(), 500);

                    const el = document.querySelector(`[aria-label="${name}"]`)
                        || document.querySelector(".blocklyTreeRow");

                    if (el) {
                        try {
                            el.scrollIntoView({ behavior: 'auto', block: 'nearest', inline: 'nearest' });
                        } catch (e) {}
                        const c = center(el);
                        // Point at the right edge of the category item
                        const r = el.getBoundingClientRect();
                        this.place(r.right, c.y);
                        this.addRing(c.x, c.y);
                    }

                    return;
                }
            }

            if (!this.dead) {
                setTimeout(tryFind, 200);
            }
        };

        tryFind();
    }

    /* ─────────────────────────────
       FLYOUT (FIXED RETRY + SAFE SVG)
    ───────────────────────────── */    goFlyout() {
        if (this.dead) return;

        const updatePosition = () => {
            if (this.dead) return;

            const flyout = this.ws.getFlyout?.();
            const flyoutWs = flyout?.getWorkspace?.();
            const isVisible = flyout?.isVisible?.() && flyoutWs;

            if (!isVisible) {
                if (this.hand) this.hand.style.display = "none";
                if (this.ring) this.ring.style.display = "none";
                setTimeout(updatePosition, 200);
                return;
            }

            const blocks = flyoutWs.getAllBlocks(false) || [];
            const target = blocks.find(b => b.type === this.block.type);

            if (target) {
                const svg = target.getSvgRoot?.();
                if (svg) {
                    const rect = svg.getBoundingClientRect();
                    const inViewport = rect.width > 0 && rect.height > 0 && 
                                       rect.right > 0 && rect.bottom > 0 && 
                                       rect.left < window.innerWidth && rect.top < window.innerHeight;

                    if (inViewport) {
                        if (this.hand) {
                            this.hand.style.display = "block";
                            this.place(rect.left, rect.top + rect.height / 2);
                        }
                        if (this.ring) {
                            this.ring.style.display = "block";
                            this.ring.style.left = (rect.left + rect.width / 2) + "px";
                            this.ring.style.top = (rect.top + rect.height / 2) + "px";
                        } else {
                            this.addRing(rect.left + rect.width / 2, rect.top + rect.height / 2);
                        }
                    } else {
                        if (this.hand) this.hand.style.display = "none";
                        if (this.ring) this.ring.style.display = "none";
                    }
                } else {
                    if (this.hand) this.hand.style.display = "none";
                    if (this.ring) this.ring.style.display = "none";
                }
            } else {
                if (this.hand) this.hand.style.display = "none";
                if (this.ring) this.ring.style.display = "none";
            }

            setTimeout(updatePosition, 200);
        };

        updatePosition();
    }
    /* ─────────────────────────────
       RING
    ───────────────────────────── */

    addRing(x, y) {
        if (this.ring) this.ring.remove();

        this.ring = document.createElement("div");
        this.ring.className = "kido-ring";
        this.ring.style.left = x + "px";
        this.ring.style.top = y + "px";

        document.body.appendChild(this.ring);
    }

    /* ─────────────────────────────
       WATCH WORKSPACE (FIXED)
    ───────────────────────────── */

    watch() {
        this.ws.addChangeListener((e) => {
            if (this.dead) return;

            if (e.type === Blockly.Events.BLOCK_CREATE) {
                const b = this.ws.getBlockById(e.blockId);
                if (b && b.type === this.block.type) {
                    this.destroy();
                }
            }
        });
    }

    destroy() {
        this.dead = true;
        this.hand?.remove();
        this.ring?.remove();
    }
}

/* ─────────────────────────────
   PUBLIC API (IMPORTANT FIX)
───────────────────────────── */

export function attachHandHint(workspace, block) {
    if (activeHand) {
        activeHand.destroy();
    }

    if (!workspace || !block) {
        console.warn("❌ Missing workspace/block");
        return;
    }

    activeHand = new MagicHand(workspace, block);
    activeHand.start();

    return activeHand;
}

export function clearHandHint() {
    if (activeHand) {
        activeHand.destroy();
        activeHand = null;
    }
}
