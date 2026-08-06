
import {
    useCallback,
    useEffect,
} from 'react';

/**
 * useCostumeManagement – costume list CRUD, mode conversion, and keyboard shortcuts.
 *
 * Accepts shared state/refs from the parent component; returns action
 * callbacks that the parent wires into the sidebar and toolbar UI.
 */
export function useCostumeManagement({
    sprite, costume, costumes, setCostumes,
    activeIdx, setActiveIdx,
    isVector, setTool,
    undoStack, redoStack,
    fabricRef, cvRef,
    setCostumeName,
    _force,
    // Vector actions (from useVectorCanvas)
    handleUndo, handleRedo, handleDeleteSel, handleCopy, handlePaste,
    // Bitmap actions (from useBitmapCanvas)
    bitmapUndo, bitmapRedo,
}) {
    // ══════════════════════════════════════════════════════════════════════════
    // MODE CONVERSION
    // ══════════════════════════════════════════════════════════════════════════

    /** Vector → Bitmap: rasterise Fabric canvas to pixel canvas */
    const convertToBitmap = useCallback(() => {
        if (!isVector || !fabricRef.current) return;
        const dataUrl = fabricRef.current.toDataURL({ format: 'png', quality: 1, multiplier: 1 });
        const img = new Image();
        img.onload = () => {
            /* MUTATION: sprite is mutated directly here */
            costume.mode = 'bitmap';
            costume.fabricJSON = null;
            costume.img = img;
            sprite.img = img;
            setCostumes([...sprite.costumes]);
            setTool('brush');
            _force(x => x + 1);
        };
        img.src = dataUrl;
    }, [isVector, costume, sprite, _force, fabricRef, setCostumes, setTool]);

    /** Bitmap → Vector: wrap rasterised image as a Fabric image */
    const convertToVector = useCallback(() => {
        if (isVector || !cvRef.current) return;
        const dataUrl = cvRef.current.toDataURL('image/png');
        const img = new Image();
        img.onload = () => {
            /* MUTATION: sprite is mutated directly here */
            costume.mode = 'vector';
            costume.bitmapData = null;
            costume.img = img;
            sprite.img = img;
            costume.fabricJSON = null; // will be loaded fresh
            setCostumes([...sprite.costumes]);
            setTool('select');
            _force(x => x + 1);
        };
        img.src = dataUrl;
    }, [isVector, costume, sprite, _force, cvRef, setCostumes, setTool]);

    // ══════════════════════════════════════════════════════════════════════════
    // COSTUME LIST MANAGEMENT
    // ══════════════════════════════════════════════════════════════════════════

    const switchCostume = useCallback((idx) => {
        /* MUTATION: sprite is mutated directly here */
        sprite.currentCostume = idx;
        sprite.img = costumes[idx]?.img || null;
        undoStack.current = []; redoStack.current = [];
        setActiveIdx(idx);
        setTool(costumes[idx]?.mode === 'bitmap' ? 'brush' : 'select');
        _force(x => x + 1);
    }, [sprite, costumes, undoStack, redoStack, setActiveIdx, setTool, _force]);

    const deleteCostume = useCallback((e, idx) => {
        e.stopPropagation();
        if (costumes.length <= 1) return;
        const next = costumes.filter((_, i) => i !== idx);
        /* MUTATION: sprite is mutated directly here */
        sprite.costumes = next;
        const newIdx = Math.min(activeIdx, next.length - 1);
        sprite.currentCostume = newIdx;
        sprite.img = next[newIdx]?.img || null;
        setCostumes(next);
        setActiveIdx(newIdx);
        _force(x => x + 1);
    }, [sprite, costumes, activeIdx, setCostumes, setActiveIdx, _force]);

    const paintNew = useCallback(() => {
        const name = `costume${costumes.length + 1}`;
        const c = {
            id: 'c_' + Date.now(), name,
            img: null, emoji: '', fabricJSON: null,
            mode: 'vector', bitmapData: null,
        };
        const next = [...costumes, c];
        /* MUTATION: sprite is mutated directly here */
        sprite.costumes = next;
        sprite.currentCostume = next.length - 1;
        setCostumes(next);
        switchCostume(next.length - 1);
    }, [sprite, costumes, setCostumes, switchCostume]);

    const handleUpload = useCallback((e) => {
        const file = e.target.files[0]; if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            const img = new Image();
            img.src = ev.target.result;
            img.onload = () => {
                const c = {
                    id: 'c_' + Date.now(),
                    name: file.name.replace(/\.[^.]+$/, ''),
                    img, fabricJSON: null, mode: 'vector', bitmapData: null,
                };
                const next = [...costumes, c];
                /* MUTATION: sprite is mutated directly here */
                sprite.costumes = next;
                sprite.currentCostume = next.length - 1;
                setCostumes(next);
                switchCostume(next.length - 1);
            };
        };
        reader.readAsDataURL(file);
        e.target.value = '';
    }, [sprite, costumes, setCostumes, switchCostume]);

    const changeName = useCallback((e) => {
        setCostumeName(e.target.value);
        /* MUTATION: sprite is mutated directly here */
        if (costume) costume.name = e.target.value;
        setCostumes([...sprite.costumes]);
    }, [sprite, costume, setCostumeName, setCostumes]);

    // ── Global keyboard shortcuts ──────────────────────────────────────────────
    useEffect(() => {
        const onKey = (e) => {
            const tag = e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA') return;

            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
                e.preventDefault();
                isVector ? handleUndo() : bitmapUndo();
            }
            if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) {
                e.preventDefault();
                isVector ? handleRedo() : bitmapRedo();
            }
            if (e.key === 'Delete' || e.key === 'Backspace') {
                if (isVector && fabricRef.current?.getActiveObjects().length) {
                    e.preventDefault(); handleDeleteSel();
                }
            }
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') { if (isVector) handleCopy(); }
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') { if (isVector) handlePaste(); }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [isVector, handleUndo, handleRedo, handleDeleteSel, handleCopy, handlePaste, bitmapUndo, bitmapRedo, fabricRef]);

    return {
        convertToBitmap,
        convertToVector,
        switchCostume,
        deleteCostume,
        paintNew,
        handleUpload,
        changeName,
    };
}
