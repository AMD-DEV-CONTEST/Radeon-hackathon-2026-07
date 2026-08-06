/* ─────────────────────────────────────────────
   BLOCK POINTER ENGINE (FINAL STABLE VERSION)
───────────────────────────────────────────── */
import { attachHandHint } from "./SpriteGuideAgent";
let lastHighlighted = null;

const FALLBACK_BLOCK_META = {
    "s_when_flag": { type: "s_when_flag", category: "Events", label: "when green flag clicked" },
    "s_when_key": { type: "s_when_key", category: "Events", label: "when key pressed" },
    "s_when_clicked": { type: "s_when_clicked", category: "Events", label: "when sprite clicked" },
    "s_broadcast": { type: "s_broadcast", category: "Events", label: "broadcast message" },
    "s_move": { type: "s_move", category: "Motion", label: "move 10 steps" },
    "s_turn_r": { type: "s_turn_r", category: "Motion", label: "turn right 15 degrees" },
    "s_turn_l": { type: "s_turn_l", category: "Motion", label: "turn left 15 degrees" },
    "s_goto": { type: "s_goto", category: "Motion", label: "go to x: 0 y: 0" },
    "s_change_x": { type: "s_change_x", category: "Motion", label: "change x by 10" },
    "s_change_y": { type: "s_change_y", category: "Motion", label: "change y by 10" },
    "s_bounce": { type: "s_bounce", category: "Motion", label: "if on edge, bounce" },
    "s_repeat": { type: "s_repeat", category: "Control", label: "repeat 10" },
    "s_forever": { type: "s_forever", category: "Control", label: "forever" },
    "s_if": { type: "s_if", category: "Control", label: "if then" },
    "s_if_else": { type: "s_if_else", category: "Control", label: "if then else" },
    "s_wait": { type: "s_wait", category: "Control", label: "wait 1 seconds" },
    "s_say": { type: "s_say", category: "Looks", label: "say Hello!" },
    "s_say_time": { type: "s_say_time", category: "Looks", label: "say Hello! for 2 seconds" },
    "s_think": { type: "s_think", category: "Looks", label: "think Hmm..." },
    "s_switch_costume": { type: "s_switch_costume", category: "Looks", label: "switch costume to" },
    "s_next_costume": { type: "s_next_costume", category: "Looks", label: "next costume" },
    "s_change_size": { type: "s_change_size", category: "Looks", label: "change size by 10" },
    "s_show": { type: "s_show", category: "Looks", label: "show" },
    "s_hide": { type: "s_hide", category: "Looks", label: "hide" },
    "s_touching": { type: "s_touching", category: "Sensing", label: "touching mouse-pointer?" },
    "s_add": { type: "s_add", category: "Operators", label: "addition" },
    "s_set_var": { type: "s_set_var", category: "Variables", label: "set variable to" },
};

/* ─────────────────────────────────────────────
   MAIN ENTRY
───────────────────────────────────────────── */

export async function highlightNextBlock(blockType, ws, BLOCK_DB) {
    if (!blockType || !ws) return;

    console.log("🎯 Highlighting block & triggering Cat Agent:", blockType);

    const meta = getMeta(blockType, BLOCK_DB);

    openCategory(ws, meta.category);

    const flyoutWs = await waitForFlyoutBlocks(ws);
    if (flyoutWs) {
        const blocks = flyoutWs.getAllBlocks(false);
        const target = blocks.find(b => b.type === blockType);
        if (target) {
            scrollToBlock(flyoutWs, target);
            glowBlock(target);
        }
    }

    // Trigger the Cat Agent drag and drop animation!
    attachHandHint(ws, {
        type: blockType,
        category: meta.category,
        label: meta.label
    });
}

/* ─────────────────────────────────────────────
   WAIT FOR FLYOUT (CRITICAL FIX)
───────────────────────────────────────────── */

/* ─────────────────────────────────────────────
   WAIT FOR FLYOUT (CRITICAL FIX)
───────────────────────────────────────────── */

function waitForFlyout(ws) {
    return new Promise(resolve => {
        let attempts = 0;

        const check = () => {
            const flyout = ws.getFlyout?.();
            const ready = flyout?.getWorkspace()?.getAllBlocks(false)?.length > 0;

            if (ready || attempts > 10) {
                resolve();
            } else {
                attempts++;
                requestAnimationFrame(check);
            }
        };

        check();
    });
}

function waitForFlyoutBlocks(ws) {
    return new Promise(resolve => {
        let attempts = 0;
        const MAX_ATTEMPTS = 30; // ~500ms total

        function check() {
            const flyout = ws.getFlyout?.();
            const flyoutWs = flyout?.getWorkspace();

            const blocks = flyoutWs?.getAllBlocks(false) || [];

            if (blocks.length > 0) {
                console.log("✅ Flyout ready with blocks");
                return resolve(flyoutWs);
            }

            if (attempts >= MAX_ATTEMPTS) {
                console.warn("⏳ Flyout timeout");
                return resolve(null);
            }

            attempts++;
            requestAnimationFrame(check);
        }

        check();
    });
}
/* ─────────────────────────────────────────────
   OPEN CATEGORY (ROBUST)
───────────────────────────────────────────── */

function openCategory(ws, categoryName) {
    if (!ws || !categoryName) return;
    const search = categoryName.toLowerCase();
    const toolbox = ws.getToolbox?.();
    if (toolbox) {
        const items = toolbox.getToolboxItems?.() || [];
        for (let item of items) {
            const name = (item.getName?.() || item.toolboxItemDef_?.name || '').toLowerCase();
            if (name && name.includes(search)) {
                console.log("📂 Opening category:", categoryName);
                try { toolbox.setSelectedItem(item); } catch (_) {}
                break;
            }
        }
    }
    const catEls = document.querySelectorAll('.blocklyTreeRow, .blocklyToolboxCategory, [role="treeitem"]');
    for (const el of catEls) {
        const text = (el.getAttribute('aria-label') || el.textContent || '').toLowerCase();
        if (text.includes(search)) {
            try { el.click(); } catch (_) {}
            return;
        }
    }
}

/* ─────────────────────────────────────────────
   SCROLL FIX (SAFE)
───────────────────────────────────────────── */

function scrollToBlock(flyoutWs, block) {
    const metrics = flyoutWs.getMetrics();
    if (!metrics) return;

    const pos = block.getRelativeToSurfaceXY();

    flyoutWs.scrollbar?.set(
        pos.x - metrics.viewWidth / 2,
        pos.y - metrics.viewHeight / 2
    );
}

/* ─────────────────────────────────────────────
   GLOW EFFECT (CLEAN)
───────────────────────────────────────────── */

function glowBlock(block) {
    clearGlow();

    const svg = block.getSvgRoot();
    if (!svg) return;

    svg.classList.add("next-block-glow");
    lastHighlighted = svg;

    console.log("✨ Glow applied to:", block.type);
}

export function clearGlow() {
    if (lastHighlighted) {
        lastHighlighted.classList.remove("next-block-glow");
        lastHighlighted = null;
    }
}

/* ─────────────────────────────────────────────
   META LOOKUP (STRICT — USES BLOCK_DB ONLY)
───────────────────────────────────────────── */

function getMeta(type, BLOCK_DB) {
    if (BLOCK_DB) {
        for (const key in BLOCK_DB) {
            if (BLOCK_DB[key]?.type === type) {
                return BLOCK_DB[key];
            }
        }
    }
    if (FALLBACK_BLOCK_META[type]) {
        return FALLBACK_BLOCK_META[type];
    }
    let cat = "Motion";
    if (type.startsWith("s_when") || type.includes("broadcast")) cat = "Events";
    else if (type.startsWith("s_if") || type.includes("repeat") || type.includes("forever") || type.includes("wait")) cat = "Control";
    else if (type.includes("say") || type.includes("costume") || type.includes("size") || type.includes("show") || type.includes("hide")) cat = "Looks";
    else if (type.includes("touching") || type.includes("key")) cat = "Sensing";
    
    return { type, category: cat, label: type.replace(/^s_/, '').replace(/_/g, ' ') };
}