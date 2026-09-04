import * as Blockly from 'blockly';
import { CatSprite, sparkles } from './CatSprite';

let activeAgent = null;

/* ───────────────────────────────────────────────────────────────
   UTILITIES
   ─────────────────────────────────────────────────────────────── */
const sleep = ms => new Promise(r => setTimeout(r, ms));

function waitForFlyoutBlock(ws, type, maxMs = 2500) {
    return new Promise(res => {
        const t0 = Date.now();
        (function tick() {
            const b = ws.getFlyout?.()?.getWorkspace?.()
                ?.getAllBlocks?.(false)?.find(b => b.type === type);
            if (b) return res(b);
            if (Date.now() - t0 > maxMs) return res(null);
            requestAnimationFrame(tick);
        })();
    });
}

/**
 * Polls getRect() every animation frame until the returned rect stops
 * changing for two consecutive frames (i.e. Blockly's flyout layout
 * pass has actually finished), or maxTries is hit.
 *
 * WHY THIS EXISTS: Blockly populates a flyout's blocks one at a time
 * and then reflows/repositions them as a batch. If code reads a
 * block's getBoundingClientRect() the instant the block object is
 * found (even after a short fixed sleep), it can catch a transient,
 * not-yet-final position — which is exactly what caused the cat to
 * visually target the SECOND flyout block's resting spot while trying
 * to grab the FIRST one. Waiting for the rect to be stable removes the
 * race entirely, regardless of how long the flyout's animation takes.
 */
function waitForStableRect(getRect, { maxTries = 30, stableFramesNeeded = 2 } = {}) {
    return new Promise(resolve => {
        let lastRect = null;
        let stableCount = 0;
        let tries = 0;

        const closeEnough = (a, b) =>
            a && b &&
            Math.abs(a.left - b.left) < 0.5 &&
            Math.abs(a.top - b.top) < 0.5 &&
            Math.abs(a.width - b.width) < 0.5 &&
            Math.abs(a.height - b.height) < 0.5;

        function tick() {
            const r = getRect();
            tries++;

            if (r && r.width > 0 && r.height > 0 && closeEnough(r, lastRect)) {
                stableCount++;
            } else {
                stableCount = 0;
            }
            lastRect = r;

            if (stableCount >= stableFramesNeeded || tries >= maxTries) {
                return resolve(lastRect);
            }
            requestAnimationFrame(tick);
        }
        tick();
    });
}

function openCategory(ws, name) {
    if (!ws || !name) return;
    const search = name.toLowerCase();
    const toolbox = ws.getToolbox?.();
    if (toolbox) {
        const items = toolbox.getToolboxItems?.() || [];
        for (const item of items) {
            const itemName = (item.getName?.() || item.toolboxItemDef_?.name || '').toLowerCase();
            if (itemName && itemName.includes(search)) {
                try {
                    toolbox.setSelectedItem(item);
                    const flyout = ws.getFlyout?.();
                    if (flyout) {
                        flyout.setVisible?.(true);
                        if (typeof item.getContents === 'function') {
                            flyout.show?.(item.getContents());
                        }
                    }
                } catch (e) {
                    console.warn("⚠️ Category select error:", e);
                }
                break;
            }
        }
    }
    const catEls = document.querySelectorAll('.blocklyTreeRow, .blocklyToolboxCategory, .blocklyTreeLabel, [role="treeitem"]');
    for (const el of catEls) {
        const text = (el.getAttribute('aria-label') || el.textContent || '').toLowerCase();
        if (text.includes(search)) {
            try {
                const row = el.closest('.blocklyTreeRow, .blocklyToolboxCategory') || el;
                row.click?.();
                row.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
                row.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
                row.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            } catch (_) {}
            return el;
        }
    }
    return null;
}

/* ───────────────────────────────────────────────────────────────
   EDITOR & CONTENT BOUNDS
   ─────────────────────────────────────────────────────────────── */
function getEditorRect(ws) {
    const svg = ws.getParentSvg?.();
    return svg?.getBoundingClientRect()
        ?? document.querySelector('.injectionDiv')?.getBoundingClientRect()
        ?? null;
}

function getContentAreaRect(ws) {
    const edRect = getEditorRect(ws);
    if (!edRect) return null;

    const tbEl = document.querySelector('.blocklyToolboxDiv');
    const flyoutEl = document.querySelector('.blocklyFlyout');

    const tbW = tbEl?.offsetWidth ?? 60;
    const flyoutRect = flyoutEl?.getBoundingClientRect();
    const flyoutW = (flyoutRect && flyoutRect.width > 0) ? flyoutRect.width : 280;

    const totalSidebarRight = Math.max((edRect.left + tbW + flyoutW), (flyoutRect?.right ?? 0));

    const visLeft = totalSidebarRight + 50;
    const visRight = edRect.right - 50;
    const visTop = edRect.top + 60;
    const visBottom = edRect.bottom - 60;

    const cx = Math.max(visLeft + 80, visLeft + (visRight - visLeft) * 0.4);
    const cy = visTop + (visBottom - visTop) * 0.35;

    return {
        left: visLeft, right: visRight,
        top: visTop, bottom: visBottom,
        cx: cx,
        cy: cy,
    };
}

/* ───────────────────────────────────────────────────────────────
   COORDINATE HELPERS
   ─────────────────────────────────────────────────────────────── */
function wsToScreen(ws, wx, wy) {
    const svg = ws.getParentSvg?.(), canvas = ws.getCanvas?.();
    if (!svg || !canvas) return null;
    try {
        const matrix = canvas.getScreenCTM();
        if (!matrix) return null;
        const pt = svg.createSVGPoint();
        pt.x = wx; pt.y = wy;
        const screenPt = pt.matrixTransform(matrix);
        return { x: screenPt.x, y: screenPt.y };
    } catch (_) {
        try {
            const ctm = canvas.getCTM(), r = svg.getBoundingClientRect();
            return {
                x: r.left + ctm.a * wx + ctm.c * wy + ctm.e,
                y: r.top + ctm.b * wx + ctm.d * wy + ctm.f
            };
        } catch (__) { return null; }
    }
}

function screenToWs(ws, sx, sy) {
    const svg = ws.getParentSvg?.(), canvas = ws.getCanvas?.();
    if (!svg || !canvas) return { x: 200, y: 100 };
    try {
        const matrix = canvas.getScreenCTM()?.inverse();
        if (!matrix) return { x: 200, y: 100 };
        const pt = svg.createSVGPoint();
        pt.x = sx; pt.y = sy;
        const wsPt = pt.matrixTransform(matrix);
        return { x: wsPt.x, y: wsPt.y };
    } catch (_) { return { x: 200, y: 100 }; }
}

/* ───────────────────────────────────────────────────────────────
   CHAIN TAIL DETECTION
   ─────────────────────────────────────────────────────────────── */
const HAT_TYPES = [
    's_when_flag', 's_when_key', 's_when_clicked', 's_when_receive',
    's_when_clone', 's_when_sprite_clicked',
    'event_whenflagclicked', 'event_whenkeypressed',
];

function findChainTail(ws) {
    const roots = ws.getAllBlocks(false).filter(b => !b.getParent?.());
    let best = null, bestDepth = -1, bestIsHat = false;
    for (const root of roots) {
        let tail = root; while (tail.getNextBlock?.()) tail = tail.getNextBlock();
        if (!tail.nextConnection) continue;
        const isHat = HAT_TYPES.includes(root.type);
        let d = 0, b = root; while (b) { d++; b = b.getNextBlock?.(); }
        if ((!bestIsHat && isHat) || (isHat === bestIsHat && d > bestDepth)) { best = tail; bestDepth = d; bestIsHat = isHat; }
    }
    return best;
}

function tailConnectionScreenPos(ws, block) {
    if (!block?.nextConnection) return null;
    try {
        const pos = block.getRelativeToSurfaceXY?.();
        const sz = block.getHeightWidth?.();
        if (!pos || !sz) return null;
        return wsToScreen(ws, pos.x + sz.width * 0.5, pos.y + sz.height);
    } catch (_) { return null; }
}

const blockRect = block => block?.getSvgRoot?.()?.getBoundingClientRect() ?? null;

function placeAndConnect(ws, blockType, tailBlock, fallbackScreen, sourceBlock) {
    let wsX = null, wsY = null;
    if (tailBlock) {
        const pos = tailBlock.getRelativeToSurfaceXY?.();
        const sz = tailBlock.getHeightWidth?.();
        if (pos && sz) { wsX = pos.x; wsY = pos.y + sz.height + 2; }
    }
    if (wsX == null && fallbackScreen) {
        const c = screenToWs(ws, fallbackScreen.x, fallbackScreen.y);
        wsX = c.x; wsY = c.y;
    }
    if (wsX == null) { wsX = 140; wsY = 100; }

    let newBlock = null;

    try {
        if (sourceBlock && typeof Blockly.Xml.blockToDom === 'function') {
            // ── Preferred path: clone the real flyout block (with shadows) ──
            const xmlEl = Blockly.Xml.blockToDom(sourceBlock, /* opt_noId */ true);
            xmlEl.setAttribute('x', Math.round(wsX));
            xmlEl.setAttribute('y', Math.round(wsY));
            newBlock = Blockly.Xml.domToBlock(xmlEl, ws);
            // v11: force the position explicitly — domToBlock doesn't
            // reliably apply the x/y attributes set above.
            if (newBlock?.moveTo) {
                try { newBlock.moveTo(new Blockly.utils.Coordinate(wsX, wsY)); }
                catch (_) {
                    // Older Blockly versions: moveTo(x, y) signature instead of Coordinate.
                    try { newBlock.moveTo(wsX, wsY); } catch (_) { }
                }
            } else if (newBlock?.moveBy) {
                const cur = newBlock.getRelativeToSurfaceXY?.() ?? { x: 0, y: 0 };
                try { newBlock.moveBy(wsX - cur.x, wsY - cur.y); } catch (_) { }
            }
        } else {
            // ── Fallback (legacy behaviour): bare type-only block. ──
            // NOTE: this path will NOT have default shadow values
            // (e.g. numeric "10") — only used if sourceBlock is unavailable.
            const dom = Blockly.utils.xml.textToDom(
                `<xml><block type="${blockType}" x="${Math.round(wsX)}" y="${Math.round(wsY)}"></block></xml>`);
            Blockly.Xml.domToWorkspace(dom, ws);
            newBlock = ws.getAllBlocks(false)
                .filter(b => b.type === blockType && !b.getParent?.()).pop();
        }
    } catch (e) {
        console.warn('⚠️ SpriteAgent: place failed', e);
        return null;
    }

    if (tailBlock && newBlock) {
        try {
            if (tailBlock.nextConnection && newBlock.previousConnection)
                tailBlock.nextConnection.connect(newBlock.previousConnection);
        } catch (_) { }
    }
    return newBlock;
}

class SpriteAgent {
    constructor(ws, blockMeta) {
        this.ws = ws; this.block = blockMeta;
        this.dead = false; this.editorRect = null;
        this.cat = null;
    }

    async run() {
        this.editorRect = getEditorRect(this.ws);
        this.cat = new CatSprite(this.editorRect);
        this.cat.createSprite();
        this.cat.createGhost(this.block.label || this.block.type, this.block.category || 'Motion');

        openCategory(this.ws, this.block.category);
        await sleep(250); if (this.dead) return;

        const catEl = this._findCategoryEl(this.block.category);
        const catRect = catEl?.getBoundingClientRect();
        const startX = (catRect && catRect.left > 0) ? catRect.right + 18 : (this.editorRect?.left ?? 0) + 45;
        const startY = (catRect && catRect.top > 0) ? catRect.top + catRect.height / 2 : (this.editorRect?.top ?? 0) + 110;

        this.cat.teleport(startX, startY);
        this.cat.setState('idle');
        await sleep(250); if (this.dead) return;

        const flyoutBlock = await waitForFlyoutBlock(this.ws, this.block.type, 2000);
        if (this.dead) return;

        let grabX = startX + 60;
        let grabY = startY + 15;

        if (flyoutBlock) {
            try { flyoutBlock.getSvgRoot?.()?.scrollIntoView({ block: 'nearest' }); } catch (_) { }
            const flyoutSvg = flyoutBlock.getSvgRoot?.();
            if (flyoutSvg) {
                const flyoutRect = await waitForStableRect(() => flyoutSvg.getBoundingClientRect());
                if (flyoutRect && flyoutRect.width > 0) {
                    grabX = flyoutRect.left + 4;
                    grabY = flyoutRect.top + flyoutRect.height / 2;
                }
            }
        }

        this.cat.setState('run');
        await this.cat.animateTo(startX, startY, grabX, grabY, 22, 12, () => this.dead, true);
        if (this.dead) return;

        const tailBlock = findChainTail(this.ws);
        let dropSx, dropSy, willConnect = false;

        if (tailBlock) {
            const snap = tailConnectionScreenPos(this.ws, tailBlock);
            const content = getContentAreaRect(this.ws);
            if (snap) {
                if (content && snap.x < content.left) {
                    dropSx = content.cx;
                    dropSy = content.cy;
                    willConnect = false;
                } else {
                    dropSx = snap.x; dropSy = snap.y;
                    willConnect = true;
                    this.cat.showSnapTarget(blockRect(tailBlock));
                }
            }
        }
        if (!willConnect) {
            const content = getContentAreaRect(this.ws);
            dropSx = content?.cx ?? (this.editorRect
                ? this.editorRect.left + 480
                : window.innerWidth * 0.55);
            dropSy = content?.cy ?? (this.editorRect
                ? this.editorRect.top + 200
                : window.innerHeight * 0.5);
        }

        await sleep(80); if (this.dead) return;

        this.cat.placeByPaw(grabX, grabY);
        const grabPromise = this.cat.playOnce('grab');
        await sleep(320); if (this.dead) return;
        this.cat.showGhost();
        await grabPromise; if (this.dead) return;

        this.cat.setState('drag');

        await this.cat.animateDrag(grabX, grabY, dropSx, dropSy, 75, 14, () => this.dead);
        if (this.dead) return;

        const placedBlock = placeAndConnect(this.ws, this.block.type,
            willConnect ? tailBlock : null, { x: dropSx, y: dropSy }, flyoutBlock);

        this.cat.removeSnapTarget();
        this.cat.hideGhost();
        sparkles(dropSx, dropSy);

        await sleep(40);
        const finalRect = blockRect(placedBlock);
        if (finalRect) {
            this.cat.anchorToBlockRect(finalRect);
        } else {
            this.cat.placeByPawRightOf(dropSx, dropSy);
        }

        await this.cat.playOnce('cheer');
        this.destroy();
    }

    _findCategoryEl(name) {
        const search = (name || '').toLowerCase();
        for (const el of document.querySelectorAll('[role="treeitem"],.blocklyTreeRow,.blocklyToolboxCategory')) {
            const lbl = (el.getAttribute('aria-label') || el.textContent || '').toLowerCase();
            if (lbl.includes(search)) return el;
        }
        return document.querySelector('.blocklyToolboxDiv') || null;
    }

    destroy() {
        this.dead = true;
        this.cat?.destroy();
        this.cat = null;
    }
}

/* ───────────────────────────────────────────────────────────────
   PUBLIC API
   ─────────────────────────────────────────────────────────────── */
export function attachHandHint(workspace, block) {
    activeAgent?.destroy(); activeAgent = null;
    if (!workspace || !block) return;
    activeAgent = new SpriteAgent(workspace, block);
    activeAgent.run().catch(e => console.warn('⚠️ SpriteAgent:', e));
    return activeAgent;
}

export function clearHandHint() {
    activeAgent?.destroy(); activeAgent = null;
}