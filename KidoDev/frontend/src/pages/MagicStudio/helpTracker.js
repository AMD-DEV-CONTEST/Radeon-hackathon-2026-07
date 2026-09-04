// helpTracker.js
// ─────────────────────────────────────────────
// Tracks which block types the user requested
// help for during the current lesson session.
// ─────────────────────────────────────────────

const _helpedBlocks = new Set();   // block types user got help for
const _placedWithHelp = new Set(); // block types that were placed AFTER help was given

let _pendingHelpType = null;       // the block type the user just got a hint for

/**
 * Call this when the user clicks Help/Guide and a hint is shown for a block type.
 */
export function recordHelpRequested(blockType) {
    if (!blockType) return;
    _helpedBlocks.add(blockType);
    _pendingHelpType = blockType;
    console.log(`[HelpTracker] Help requested for: ${blockType}`);
}

/**
 * Call this when a block is added to the workspace.
 * If the last help was for this block type, mark it as "placed with help".
 */
export function recordBlockPlaced(blockType) {
    if (!blockType) return;
    if (_pendingHelpType && _pendingHelpType === blockType) {
        _placedWithHelp.add(blockType);
        _pendingHelpType = null;
        console.log(`[HelpTracker] Block placed WITH help: ${blockType}`);
    }
}

/**
 * Returns a Set of block types that were placed after the user asked for help.
 */
export function getHelpedBlockTypes() {
    return new Set(_placedWithHelp);
}

/**
 * Returns how many of the given required block types were placed with help.
 */
export function countHelpedRequired(requiredBlocks = []) {
    return requiredBlocks.filter(b => _placedWithHelp.has(b)).length;
}

/**
 * Reset all tracking — call this when a new lesson starts or workspace is cleared.
 */
export function resetHelpTracking() {
    _helpedBlocks.clear();
    _placedWithHelp.clear();
    _pendingHelpType = null;
    console.log('[HelpTracker] Reset.');
}