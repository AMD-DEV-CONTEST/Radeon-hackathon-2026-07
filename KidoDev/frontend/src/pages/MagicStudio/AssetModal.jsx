// ─── AssetModal.jsx ───────────────────────────────────────────────────────────
import React from 'react';
import { S } from './styles';
import { SPRITE_LIBRARY, BACKDROPS, getCleanAssetUrl } from './constants';
import { KIDO_SOUNDS } from './kidoAssets';
import { playSound } from './soundEngine';

export function AssetModal({
    libMode, setLibMode, libCategory, setLibCategory, searchQuery, setSearchQuery,
    scratchLibrary, scratchBackdrops, scratchSounds, loadingLib,
    switchBackdrop, spritesRef, projectBackdropsRef, projectSoundsRef,
    assetCache, _force, addLog,
}) {
    if (!libMode) return null;

    // ── Category tabs ─────────────────────────────────────────────────────────
    const categories = libMode === 'sprite'
        ? ['Kido Picks', 'All', 'animals', 'people', 'fantasy', 'dance', 'music', 'sports', 'food', 'fashion', 'letters']
        : libMode === 'backdrop'
            ? ['Kido Picks', 'All', 'indoors', 'outdoors', 'castle', 'city', 'flying', 'holiday', 'music', 'space', 'sports', 'underwater']
            : ['Kido Picks', 'All', 'animals', 'effects', 'loops', 'notes', 'percussion', 'space', 'sports', 'voice', 'wacky'];

    // ── Kido name sets ────────────────────────────────────────────────────────
    const kidoSpriteNames = new Set(['Cat', 'Dog', 'Frog', 'Monkey', 'Butterfly', 'Radio', 'Drum', 'Balloon', 'Apple', 'Ghost', 'Tree', 'Banana']);
    const kidoBackdropNames = new Set(['Bedroom 1', 'Bedroom 2', 'Bedroom 3', 'Jungle', 'Safari', 'White Stage', 'Bedroom', 'Savanna']);

    // ── Build item pool ───────────────────────────────────────────────────────
    const allItems = (() => {
        if (libMode === 'sprite') {
            const kidoLocal = SPRITE_LIBRARY.filter(s => s.tags?.includes('kido picks'));
            const kidoScratch = scratchLibrary.filter(s => kidoSpriteNames.has(s.name));
            const others = scratchLibrary.filter(s => !kidoSpriteNames.has(s.name));
            return [...kidoLocal, ...kidoScratch, ...others];
        }
        if (libMode === 'backdrop') {
            // Local BACKDROPS come first (they have pre-loaded images).
            // Then append Scratch CDN backdrops that aren't already in the local list.
            const localNames = new Set(BACKDROPS.map(b => b.name));
            const scratchOnly = scratchBackdrops.filter(b => !localNames.has(b.name));
            return [...BACKDROPS, ...scratchOnly];
        }
        // sounds
        return [...KIDO_SOUNDS, ...scratchSounds];
    })();

    // ── Filter by category + search ───────────────────────────────────────────
    const filtered = allItems.filter(s => {
        const cat = (libCategory || 'All').toLowerCase();
        const isKido = cat === 'kido picks';

        const matchKido = isKido && (
            (s.tags && s.tags.some(t => t.toLowerCase() === 'kido picks')) ||
            kidoSpriteNames.has(s.name) ||
            kidoBackdropNames.has(s.name)
        );
        const matchCat = cat === 'all'
            || (s.tags && s.tags.some(t => t.toLowerCase() === cat))
            || (s.category && s.category.toLowerCase() === cat);
        const matchSearch = (s.name || '').toLowerCase().includes((searchQuery || '').toLowerCase());

        return (isKido ? matchKido : matchCat) && matchSearch;
    });

    // ── Thumbnail URL helper ──────────────────────────────────────────────────
    //
    //  • Local BACKDROPS already store a pre-loaded `img` and a `url`.
    //  • Scratch CDN items (sprites / backdrops) carry `md5ext`.
    //
    function getThumbUrl(item) {
        // Local backdrop with a pre-baked URL
        if (item.url) return getCleanAssetUrl(item.url);
        // Scratch sprite: first costume
        if (item.costumes?.length > 0) {
            return getCleanAssetUrl(
                `https://assets.scratch.mit.edu/internalapi/asset/${item.costumes[0].md5ext}/get/`
            );
        }
        // Scratch backdrop (md5ext on the root object)
        if (item.md5ext) {
            return getCleanAssetUrl(
                `https://assets.scratch.mit.edu/internalapi/asset/${item.md5ext}/get/`
            );
        }
        return null;
    }

    // ── Selection handler ─────────────────────────────────────────────────────
    const handleSelect = (s) => {
        // ── SPRITE ────────────────────────────────────────────────────────────
        if (libMode === 'sprite') {
            const isScratchSprite = s.costumes?.length > 0;
            const localMatch = SPRITE_LIBRARY.find(ls => ls.name.toLowerCase() === s.name.toLowerCase());
            const emojiFallback = s.emoji || localMatch?.emoji || '⭐';

            const newSprite = {
                id: 'spr_' + Math.random().toString(36).substr(2, 6),
                name: s.name,
                emoji: emojiFallback,
                x: 240, y: 180, dir: 90, size: 100, ghost: 0,
                colorHue: 0, brightness: 0, visible: true,
                speech: null, bubbleType: 'say', img: null, xml: '',
            };

            if (isScratchSprite) {
                newSprite.md5ext = s.costumes[0].md5ext;
                newSprite.costumes = [];
                newSprite.currentCostume = 0;

                s.costumes.forEach((c, i) => {
                    const cMd5 = c.md5ext;
                    const cThumb = getCleanAssetUrl(
                        `https://assets.scratch.mit.edu/internalapi/asset/${cMd5}/get/`
                    );
                    const costumeObj = {
                        id: `costume_${i}`,
                        name: c.name || `Costume ${i + 1}`,
                        img: null,
                        emoji: '',
                    };
                    newSprite.costumes.push(costumeObj);

                    let cImg = assetCache.current[cMd5];
                    if (!cImg) {
                        cImg = new Image();
                        cImg.crossOrigin = 'anonymous';
                        cImg.onload = () => {
                            assetCache.current[cMd5] = cImg;
                            costumeObj.img = cImg;
                            if (i === 0) { newSprite.img = cImg; _force(x => x + 1); }
                        };
                        cImg.src = cThumb;
                    } else {
                        costumeObj.img = cImg;
                        if (i === 0) newSprite.img = cImg;
                    }
                });
            }

            spritesRef.current.push(newSprite);
            addLog('➕ Added ' + s.name);
            _force(x => x + 1);

            // ── BACKDROP ──────────────────────────────────────────────────────────
        } else if (libMode === 'backdrop') {
            // Check if this is a local BACKDROPS entry (has a numeric index)
            const localIndex = BACKDROPS.findIndex(b => b.name === s.name);

            if (localIndex !== -1) {
                // ── Local backdrop ────────────────────────────────────────────
                // Always re-load its image via the proxy if not yet cached,
                // then hand switchBackdrop the numeric index.
                const localBd = BACKDROPS[localIndex];

                if (localBd.md5ext && !localBd.img) {
                    // Image not yet loaded (createAssetImg may have failed due to CORS
                    // before the page was fully ready). Retry now through the proxy.
                    const proxied = getCleanAssetUrl(localBd.url);
                    let cached = assetCache.current[localBd.md5ext];
                    if (!cached) {
                        cached = new Image();
                        cached.crossOrigin = 'anonymous';
                        cached.onload = () => {
                            assetCache.current[localBd.md5ext] = cached;
                            localBd.img = cached;           // update the singleton
                            _force(x => x + 1);             // re-render canvas
                        };
                        cached.src = proxied;
                        assetCache.current[localBd.md5ext] = cached; // store pending
                    } else {
                        localBd.img = cached;
                    }
                } else if (localBd.md5ext && localBd.img) {
                    // Already loaded — make sure it's in assetCache too
                    assetCache.current[localBd.md5ext] = localBd.img;
                }

                switchBackdrop(localIndex);

            } else {
                // ── Scratch CDN backdrop ──────────────────────────────────────
                const md5ext = s.md5ext;
                const thumb = md5ext
                    ? getCleanAssetUrl(`https://assets.scratch.mit.edu/internalapi/asset/${md5ext}/get/`)
                    : null;
                const newBdId = 'bd_' + (s.id || Math.random()).toString().replace(/\./g, '');

                // Re-use an existing runtime backdrop with the same md5ext
                let existing = projectBackdropsRef.current.find(b => b.md5ext === md5ext);
                if (!existing) {
                    existing = { ...s, id: newBdId, img: null, md5ext };
                    projectBackdropsRef.current.push(existing);
                }

                // Load / cache the image
                if (md5ext) {
                    let img = assetCache.current[md5ext];
                    if (!img) {
                        img = new Image();
                        img.crossOrigin = 'anonymous';
                        img.onload = () => {
                            assetCache.current[md5ext] = img;
                            existing.img = img;
                            _force(x => x + 1);     // canvas re-render once loaded
                        };
                        img.src = thumb;
                        assetCache.current[md5ext] = img;   // store pending img reference
                    } else {
                        existing.img = img;
                    }
                }

                // Switch to the string ID — canvas renderer must use getActiveBackdrop()
                switchBackdrop(existing.id);
            }

            addLog('🖼️ Scene changed to ' + s.name);
            _force(x => x + 1);

            // ── SOUND ─────────────────────────────────────────────────────────────
        } else if (libMode === 'sound') {
            const isKidoSound = s.md5ext === null && s.id;
            const newSndId = isKidoSound
                ? s.id
                : 'snd_' + (s.id || Math.random()).toString().replace(/\./g, '');

            projectSoundsRef.current.push({
                ...s,
                id: newSndId,
                md5ext: s.md5ext,
                synthId: isKidoSound ? s.id : null,
            });
            playSound(isKidoSound ? s.id : newSndId, projectSoundsRef.current);
            addLog('🎵 Added sound ' + s.name);
            _force(x => x + 1);
        }

        setLibMode(null);
    };

    // ── Render ────────────────────────────────────────────────────────────────
    return (
        <div style={{
            position: 'fixed', inset: 0,
            background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(5px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 9999, padding: 20,
        }}>
            <div style={{
                width: '90%', maxWidth: 1200, height: '85vh',
                background: '#fff', borderRadius: 24,
                display: 'flex', flexDirection: 'column',
                overflow: 'hidden', boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
            }}>
                {/* ── Header ── */}
                <div style={{
                    padding: '24px 32px',
                    background: 'linear-gradient(135deg, #6366F1, #4F46E5)',
                    color: '#fff',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    flexShrink: 0,
                }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 900, letterSpacing: '-0.5px' }}>
                            {libMode === 'sprite'
                                ? 'Select Your Character'
                                : libMode === 'backdrop'
                                    ? 'Choose an Adventure World'
                                    : 'Pick a Perfect Sound'}
                        </h2>
                        <p style={{ margin: 0, fontSize: 13, opacity: 0.9 }}>
                            ⭐ Kido Dev Picks + over 1,000 official Scratch assets
                        </p>
                    </div>
                    <button
                        onClick={() => setLibMode(null)}
                        style={{
                            background: 'rgba(255,255,255,0.2)', border: 'none',
                            borderRadius: '50%', width: 44, height: 44,
                            fontSize: 24, cursor: 'pointer', color: '#fff',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}
                        onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.3)'}
                        onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,255,255,0.2)'}
                    >×</button>
                </div>

                {/* ── Filter bar ── */}
                <div style={{
                    padding: '16px 32px',
                    background: '#F8FAFC', borderBottom: '1px solid #E2E8F0',
                    display: 'flex', flexDirection: 'column', gap: 16,
                }}>
                    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                        {categories.map(cat => (
                            <button
                                key={cat}
                                onClick={() => setLibCategory(cat)}
                                style={{
                                    fontSize: 13, fontWeight: 800,
                                    border: 'none', borderRadius: 20, padding: '6px 18px',
                                    background: (libCategory || 'All').toLowerCase() === cat.toLowerCase()
                                        ? '#6366F1' : '#fff',
                                    color: (libCategory || 'All').toLowerCase() === cat.toLowerCase()
                                        ? '#fff' : '#6366F1',
                                    cursor: 'pointer',
                                    boxShadow: '0 2px 8px rgba(0,0,0,0.05)',
                                    textTransform: 'capitalize',
                                    transition: 'all 0.2s',
                                }}
                            >{cat}</button>
                        ))}
                    </div>
                    <div style={{ position: 'relative' }}>
                        <span style={{
                            position: 'absolute', left: 16, top: '50%',
                            transform: 'translateY(-50%)', fontSize: 18, color: '#94A3B8',
                        }}>🔍</span>
                        <input
                            type="text"
                            placeholder={
                                libMode === 'sprite'
                                    ? 'Search for a character...'
                                    : libMode === 'backdrop'
                                        ? 'Search for a place...'
                                        : 'Search for a sound...'
                            }
                            value={searchQuery}
                            onChange={e => setSearchQuery(e.target.value)}
                            style={{
                                width: '100%', padding: '14px 16px 14px 48px',
                                borderRadius: 16, border: '2px solid #E0E7FF',
                                fontSize: 16, outline: 'none',
                                boxShadow: '0 4px 12px rgba(99,102,241,0.05)',
                                transition: 'border-color 0.2s',
                            }}
                            onFocus={e => e.target.style.borderColor = '#6366F1'}
                            onBlur={e => e.target.style.borderColor = '#E0E7FF'}
                        />
                    </div>
                </div>

                {/* ── Grid ── */}
                <div style={{
                    flex: 1, overflowY: 'auto', padding: '32px',
                    background: '#F0F4FF',
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
                    gap: 20, alignContent: 'start',
                }}>
                    {loadingLib ? (
                        <div style={{ gridColumn: '1/-1', textAlign: 'center', padding: 100, color: '#4F46E5' }}>
                            <div className="spinner-border text-primary" style={{ width: '3rem', height: '3rem' }} />
                            <h3 style={{ marginTop: 20, fontWeight: 900 }}>Loading Official Library...</h3>
                        </div>
                    ) : filtered.map((s, idx) => {
                        const thumbUrl = getThumbUrl(s);

                        return (
                            <div
                                key={idx}
                                onClick={() => handleSelect(s)}
                                style={{
                                    background: '#fff', border: '1px solid #D1D5DB',
                                    borderRadius: 16, display: 'flex', flexDirection: 'column',
                                    alignItems: 'center', cursor: 'pointer',
                                    transition: 'all 0.2s', height: 160,
                                    boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
                                    position: 'relative',
                                }}
                                onMouseEnter={e => {
                                    e.currentTarget.style.borderColor = '#4F46E5';
                                    e.currentTarget.style.backgroundColor = '#EEF2FF';
                                    e.currentTarget.style.transform = 'translateY(-4px)';
                                    e.currentTarget.style.boxShadow = '0 8px 24px rgba(79,70,229,0.15)';
                                }}
                                onMouseLeave={e => {
                                    e.currentTarget.style.borderColor = '#D1D5DB';
                                    e.currentTarget.style.backgroundColor = '#fff';
                                    e.currentTarget.style.transform = 'translateY(0)';
                                    e.currentTarget.style.boxShadow = '0 2px 4px rgba(0,0,0,0.05)';
                                }}
                            >
                                {/* Thumbnail area */}
                                <div style={{
                                    flex: 1, width: '100%',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    padding: 12, overflow: 'hidden', borderRadius: '16px 16px 0 0',
                                }}>
                                    {libMode === 'sound' ? (
                                        <div style={{ fontSize: 50 }}>🔊</div>
                                    ) : thumbUrl ? (
                                        <img
                                            src={thumbUrl}
                                            style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'cover', borderRadius: 8 }}
                                            alt={s.name}
                                            // Colour-fill fallback while image loads
                                            onError={e => { e.currentTarget.style.display = 'none'; }}
                                        />
                                    ) : (
                                        // Colour-only backdrops (White Stage, Empty) or emoji sprites
                                        s.color ? (
                                            <div style={{
                                                width: '100%', height: '100%',
                                                background: s.color, borderRadius: 8,
                                                minHeight: 80,
                                            }} />
                                        ) : (
                                            <div style={{ fontSize: 60 }}>{s.emoji}</div>
                                        )
                                    )}
                                </div>

                                {/* Name label */}
                                <div style={{
                                    width: '100%', padding: '8px 4px', textAlign: 'center',
                                    background: '#F9FAFB', borderTop: '1px solid #E5E7EB',
                                    borderBottomLeftRadius: 16, borderBottomRightRadius: 16,
                                    color: '#374151', fontSize: 12, fontWeight: 800,
                                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                                }}>{s.name}</div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}