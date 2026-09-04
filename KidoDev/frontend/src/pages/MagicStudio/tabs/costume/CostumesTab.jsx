
import React, {
    useEffect,
    useRef,
    useState,
} from 'react';
import { SC } from './costumeToolbarUI';
import { useVectorCanvas } from './useVectorCanvas';
import { useBitmapCanvas } from './useBitmapCanvas';
import { useCostumeManagement } from './useCostumeManagement';
import { CostumeSidebar } from './CostumeSidebar';
import { CostumeToolbars } from './CostumeToolbars';
import { CostumeCanvasPanel } from './CostumeCanvasPanel';

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════
export function CostumesTab({ sp, fileInputRef, _force, addLog }) {
    /* MUTATION: sprite (sp.current) is mutated directly throughout this component.
       This is flagged but intentionally NOT fixed in this refactor. */
    const sprite = sp.current;

    // ── Ensure sprite has costumes array ──────────────────────────────────────
    if (!sprite.costumes) {
        /* MUTATION: sprite is mutated directly here */
        sprite.costumes = [{
            id: 'costume1',
            name: 'Costume 1',
            img: sprite.img || null,
            emoji: sprite.emoji || '',
            fabricJSON: null,
            mode: 'vector',   // 'vector' | 'bitmap'
            bitmapData: null, // ImageData for bitmap mode
        }];
        sprite.currentCostume = 0;
    }

    // ── React state ───────────────────────────────────────────────────────────
    const [costumes, setCostumes] = useState(() => sprite.costumes);
    const [activeIdx, setActiveIdx] = useState(sprite.currentCostume || 0);
    const [tool, setTool] = useState('select');
    const [fillColor, setFillColor] = useState('#9966FF');
    const [strokeColor, setStrokeColor] = useState('#575E75');
    const [strokeWidth, setStrokeWidth] = useState(3);
    const [hasSelection, setHasSel] = useState(false);
    const [costumeName, setCostumeName] = useState('');
    const [zoom, setZoom] = useState(1);

    // Clipboard for copy/paste
    const clipboardRef = useRef(null);

    // Current costume shorthand
    const costume = costumes[activeIdx] || costumes[0];
    const isVector = costume?.mode !== 'bitmap';

    // ── Canvas refs ────────────────────────────────────────────────────────────
    const cvRef = useRef(null);
    const fabricRef = useRef(null);
    const bitmapRef = useRef(null);

    // ── History stacks ────────────────────────────────────────────────────────
    const undoStack = useRef([]);
    const redoStack = useRef([]);
    const isHistoryAction = useRef(false);

    // ── Bitmap drawing state ──────────────────────────────────────────────────
    const bmDraw = useRef({
        painting: false,
        lastX: 0, lastY: 0,
        startX: 0, startY: 0,
        snapshot: null,
        selRect: null,
        selSnapshot: null,
        moving: false,
    });

    // ── Sync costume name ──────────────────────────────────────────────────────
    useEffect(() => { setCostumeName(costume?.name || ''); }, [activeIdx, costumes]);

    // ── Hooks ─────────────────────────────────────────────────────────────────
    const {
        saveHistory, saveToSpritePreview,
        handleUndo, handleRedo, handleDeleteSel,
        handleCopy, handlePaste,
        groupSel, ungroupSel, sendLayer, flip,
    } = useVectorCanvas({
        costume, sprite, isVector, cvRef, fabricRef,
        undoStack, redoStack, isHistoryAction, clipboardRef,
        tool, setTool, fillColor, strokeColor, strokeWidth,
        setHasSel, _force, activeIdx,
    });

    const {
        saveBitmapToSprite, bitmapUndo, bitmapRedo, bitmapFlip,
    } = useBitmapCanvas({
        costume, sprite, isVector, cvRef, bitmapRef, bmDraw,
        undoStack, redoStack, isHistoryAction,
        tool, fillColor, strokeWidth, _force, activeIdx,
    });

    const {
        convertToBitmap, convertToVector,
        switchCostume, deleteCostume, paintNew,
        handleUpload, changeName,
    } = useCostumeManagement({
        sprite, costume, costumes, setCostumes,
        activeIdx, setActiveIdx,
        isVector, setTool,
        undoStack, redoStack,
        fabricRef, cvRef,
        setCostumeName,
        _force,
        handleUndo, handleRedo, handleDeleteSel, handleCopy, handlePaste,
        bitmapUndo, bitmapRedo,
    });

    // ── Render ────────────────────────────────────────────────────────────────
    return (
        <div style={{
            flex: 1, display: 'flex', flexDirection: 'row',
            background: SC.white, color: SC.text, overflow: 'hidden',
            userSelect: 'none',
            fontFamily: "'Helvetica Neue', Helvetica, Arial, sans-serif",
            fontSize: 13,
        }}>
            <CostumeSidebar
                costumes={costumes}
                activeIdx={activeIdx}
                switchCostume={switchCostume}
                deleteCostume={deleteCostume}
                paintNew={paintNew}
                handleUpload={handleUpload}
            />
            <CostumeCanvasPanel
                isVector={isVector}
                tool={tool}
                setTool={setTool}
                cvRef={cvRef}
                zoom={zoom}
                setZoom={setZoom}
                convertToBitmap={convertToBitmap}
                convertToVector={convertToVector}
            >
                <CostumeToolbars
                    costumeName={costumeName}
                    changeName={changeName}
                    isVector={isVector}
                    hasSelection={hasSelection}
                    fillColor={fillColor}
                    setFillColor={setFillColor}
                    strokeColor={strokeColor}
                    setStrokeColor={setStrokeColor}
                    strokeWidth={strokeWidth}
                    setStrokeWidth={setStrokeWidth}
                    fabricRef={fabricRef}
                    clipboardRef={clipboardRef}
                    handleUndo={handleUndo}
                    handleRedo={handleRedo}
                    bitmapUndo={bitmapUndo}
                    bitmapRedo={bitmapRedo}
                    groupSel={groupSel}
                    ungroupSel={ungroupSel}
                    sendLayer={sendLayer}
                    handleCopy={handleCopy}
                    handlePaste={handlePaste}
                    handleDeleteSel={handleDeleteSel}
                    flip={flip}
                    bitmapFlip={bitmapFlip}
                />
            </CostumeCanvasPanel>
        </div>
    );
}
