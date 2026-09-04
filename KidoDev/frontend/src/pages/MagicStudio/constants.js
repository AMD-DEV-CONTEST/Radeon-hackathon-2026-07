// ─── constants.js ────────────────────────────────────────────────────────────

export const SPRITE_LIBRARY = [
    // --- KIDO PICKS (emoji fallback; Scratch CDN versions load via AssetModal) ---
    { name: 'Cat', emoji: '🐱', category: 'Animals', tags: ['kido picks', 'animals'] },
    { name: 'Dog', emoji: '🐶', category: 'Animals', tags: ['kido picks', 'animals'] },
    { name: 'Frog', emoji: '🐸', category: 'Animals', tags: ['kido picks', 'animals'] },
    { name: 'Monkey', emoji: '🐒', category: 'Animals', tags: ['kido picks', 'animals'] },
    { name: 'Butterfly', emoji: '🦋', category: 'Animals', tags: ['kido picks', 'animals'] },
    { name: 'Radio', emoji: '📻', category: 'Music', tags: ['kido picks', 'music'] },
    { name: 'Drum', emoji: '🥁', category: 'Music', tags: ['kido picks', 'music'] },
    { name: 'Balloon', emoji: '🎈', category: 'Items', tags: ['kido picks'] },
    { name: 'Apple', emoji: '🍎', category: 'Food', tags: ['kido picks', 'food'] },
    { name: 'Ghost', emoji: '👻', category: 'Fantasy', tags: ['kido picks', 'fantasy'] },
    { name: 'Tree', emoji: '🌳', category: 'Nature', tags: ['kido picks', 'nature'] },
    { name: 'Banana', emoji: '🍌', category: 'Food', tags: ['kido picks', 'food'] },

    // --- ANIMALS ---
    { name: 'Bear', emoji: '🐻', category: 'Animals', tags: ['animals'] },
    { name: 'Fox', emoji: '🦊', category: 'Animals', tags: ['animals'] },
    { name: 'Lion', emoji: '🦁', category: 'Animals', tags: ['animals'] },
    { name: 'Tiger', emoji: '🐯', category: 'Animals', tags: ['animals'] },
    { name: 'Turtle', emoji: '🐢', category: 'Animals', tags: ['animals'] },
    { name: 'Snake', emoji: '🐍', category: 'Animals', tags: ['animals'] },
    { name: 'Elephant', emoji: '🐘', category: 'Animals', tags: ['animals'] },
    { name: 'Giraffe', emoji: '🦒', category: 'Animals', tags: ['animals'] },
    { name: 'Bird', emoji: '🐦', category: 'Animals', tags: ['animals'] },
    { name: 'Penguin', emoji: '🐧', category: 'Animals', tags: ['animals'] },
    { name: 'Fish', emoji: '🐟', category: 'Animals', tags: ['animals'] },
    { name: 'Octopus', emoji: '🐙', category: 'Animals', tags: ['animals'] },
    { name: 'Shark', emoji: '🦈', category: 'Animals', tags: ['animals'] },
    { name: 'Crab', emoji: '🦀', category: 'Animals', tags: ['animals'] },
    { name: 'Dinosaur', emoji: '🦖', category: 'Animals', tags: ['animals'] },
    { name: 'Dragon', emoji: '🐉', category: 'Animals', tags: ['animals'] },

    // --- PEOPLE & FANTASY ---
    { name: 'Boy', emoji: '👦', category: 'People', tags: ['people'] },
    { name: 'Girl', emoji: '👧', category: 'People', tags: ['people'] },
    { name: 'Wizard', emoji: '🧙', category: 'Fantasy', tags: ['fantasy'] },
    { name: 'Witch', emoji: '🧙‍♀️', category: 'Fantasy', tags: ['fantasy'] },
    { name: 'Alien', emoji: '👽', category: 'Fantasy', tags: ['fantasy'] },
    { name: 'Robot', emoji: '🤖', category: 'Fantasy', tags: ['fantasy'] },
    { name: 'Ninjia', emoji: '🥷', category: 'Fantasy', tags: ['fantasy'] },
    { name: 'Hero', emoji: '🦸', category: 'Fantasy', tags: ['fantasy'] },
    { name: 'Viking', emoji: '🧔‍♂️', category: 'Fantasy', tags: ['fantasy'] },
    { name: 'Fairy', emoji: '🧚', category: 'Fantasy', tags: ['fantasy'] },
    { name: 'Mermaid', emoji: '🧜‍♀️', category: 'Fantasy', tags: ['fantasy'] },

    // --- FOOD & ITEMS ---
    { name: 'Cake', emoji: '🍰', category: 'Food', tags: ['food'] },
    { name: 'Pizza', emoji: '🍕', category: 'Food', tags: ['food'] },
    { name: 'Burger', emoji: '🍔', category: 'Food', tags: ['food'] },
    { name: 'Ice Cream', emoji: '🍦', category: 'Food', tags: ['food'] },
    { name: 'Donut', emoji: '🍩', category: 'Food', tags: ['food'] },
    { name: 'Taco', emoji: '🌮', category: 'Food', tags: ['food'] },
    { name: 'Soccer Ball', emoji: '⚽', category: 'Items', tags: ['sports'] },
    { name: 'Laptop', emoji: '💻', category: 'Items', tags: [] },
    { name: 'Rocket', emoji: '🚀', category: 'Items', tags: [] },
    { name: 'UFO', emoji: '🛸', category: 'Items', tags: [] },
    { name: 'Bicycle', emoji: '🚲', category: 'Items', tags: [] },
    { name: 'Guitar', emoji: '🎸', category: 'Items', tags: ['music'] },
    { name: 'Gameboy', emoji: '🎮', category: 'Items', tags: [] },

    // --- NATURE ---
    { name: 'Flower', emoji: '🌸', category: 'Nature', tags: [] },
    { name: 'Cactus', emoji: '🌵', category: 'Nature', tags: [] },
    { name: 'Cloud', emoji: '☁️', category: 'Nature', tags: [] },
    { name: 'Sun', emoji: '☀️', category: 'Nature', tags: [] },
    { name: 'Moon', emoji: '🌙', category: 'Nature', tags: [] },
    { name: 'Star', emoji: '⭐', category: 'Nature', tags: [] },
    { name: 'Rain', emoji: '🌧️', category: 'Nature', tags: [] },
];

// ─── Asset URL helper ─────────────────────────────────────────────────────────
// ─── Asset URL helper ─────────────────────────────────────────────────────────

export function getCleanAssetUrl(url) {
    if (!url) return '';

    // Use Scratch asset directly
    return url;
}

// ─── Image pre-loader ─────────────────────────────────────────────────────────

const isBrowser = typeof window !== 'undefined';

function createAssetImg(url) {
    if (!url || !isBrowser) return null;

    const img = new Image();

    // IMPORTANT:
    // Do NOT use crossOrigin
    // Scratch CDN images often fail with it

    img.src = getCleanAssetUrl(url);

    img.onload = () => {
        console.log('✅ Loaded:', url);
    };

    img.onerror = (e) => {
        console.error('❌ Failed:', url, e);
    };

    return img;
}

// ─── Helper: resolve a backdrop from bdrop state ─────────────────────────────

export function getActiveBackdrop(bdrop, projectBackdropsRef) {
    if (typeof bdrop === 'number') {
        return BACKDROPS[bdrop] ?? BACKDROPS[0];
    }

    // Runtime project backdrop
    const fromProject = projectBackdropsRef?.current?.find(
        b => b.id === bdrop
    );

    if (fromProject) return fromProject;

    // Local fallback
    const fromLocal = BACKDROPS.find(
        b => b.id === bdrop || b.name === bdrop
    );

    return fromLocal ?? BACKDROPS[0];
}

// ─── BACKDROPS ────────────────────────────────────────────────────────────────
//
// Each entry has:
//   name     – display name
//   color    – solid fallback colour while image loads (or if no image)
//   md5ext   – Scratch asset hash (null for colour-only entries)
//   url      – full Scratch CDN URL (null for colour-only entries)
//   img      – pre-loaded Image object (null until loaded; MagicStudio loads them)
//   tags     – category tags used by the AssetModal filter
//
export const BACKDROPS = [
    // ── Kido Picks ────────────────────────────────────────────────────────────
    {
        name: 'White Stage',
        color: '#FFFFFF',
        md5ext: null,
        url: null,
        img: null,
        tags: ['kido picks'],
    },
    {
        name: 'Bedroom 1',
        color: '#F5DEB3',
        md5ext: '7aa6bbb2ddc4c10f901e1a50aeac1c7e.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/7aa6bbb2ddc4c10f901e1a50aeac1c7e.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/7aa6bbb2ddc4c10f901e1a50aeac1c7e.png/get/'),
        tags: ['kido picks', 'indoors'],
    },
    {
        name: 'Jungle',
        color: '#1b5e20',
        md5ext: 'f4f908da19e2753f3ed679d7b37650ca.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/f4f908da19e2753f3ed679d7b37650ca.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/f4f908da19e2753f3ed679d7b37650ca.png/get/'),
        tags: ['kido picks', 'outdoors'],
    },
    {
        name: 'Savanna',
        color: '#C2922C',
        md5ext: '9b020b8c7cb6a9592f7303add9441d8f.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/9b020b8c7cb6a9592f7303add9441d8f.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/9b020b8c7cb6a9592f7303add9441d8f.png/get/'),
        tags: ['kido picks', 'outdoors'],
    },

    // ── Standard ──────────────────────────────────────────────────────────────
    {
        name: 'Empty',
        color: '#ffffff',
        md5ext: null,
        url: null,
        img: null,
        tags: [],
    },
    {
        name: 'Blue Sky',
        color: '#87CEEB',
        md5ext: 'e7c147730f19d284bcd7b3f00af19bb6.svg',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/e7c147730f19d284bcd7b3f00af19bb6.svg/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/e7c147730f19d284bcd7b3f00af19bb6.svg/get/'),
        tags: ['outdoors', 'flying'],
    },
    {
        name: 'Space',
        color: '#020c1b',
        md5ext: '84208d9a3718ec3c9fc5a32a792fa1d0.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/84208d9a3718ec3c9fc5a32a792fa1d0.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/84208d9a3718ec3c9fc5a32a792fa1d0.png/get/'),
        tags: ['space'],
    },
    {
        name: 'Underwater 2',
        color: '#01579B',
        md5ext: '1517c21786d2d0edc2f3037408d850bd.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/1517c21786d2d0edc2f3037408d850bd.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/1517c21786d2d0edc2f3037408d850bd.png/get/'),
        tags: ['underwater'],
    },
    {
        name: 'Night City',
        color: '#1a1a2e',
        md5ext: '6fdc795ff487204f72740567be5f64f9.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/6fdc795ff487204f72740567be5f64f9.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/6fdc795ff487204f72740567be5f64f9.png/get/'),
        tags: ['city', 'outdoors'],
    },
    {
        name: 'Forest',
        color: '#2d4c1e',
        md5ext: '92968ac16b2f0c3f7835a6dacd172c7b.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/92968ac16b2f0c3f7835a6dacd172c7b.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/92968ac16b2f0c3f7835a6dacd172c7b.png/get/'),
        tags: ['outdoors'],
    },
    {
        name: 'Desert',
        color: '#eebd71',
        md5ext: 'd98a9526a34890cf4bad11b5409eae2a.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/d98a9526a34890cf4bad11b5409eae2a.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/d98a9526a34890cf4bad11b5409eae2a.png/get/'),
        tags: ['outdoors'],
    },
    {
        name: 'Slopes',
        color: '#eef6f9',
        md5ext: '63b6a69594a0a87888b56244bfa2ac1b.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/63b6a69594a0a87888b56244bfa2ac1b.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/63b6a69594a0a87888b56244bfa2ac1b.png/get/'),
        tags: ['outdoors', 'sports'],
    },
    {
        name: 'Mountain',
        color: '#5a6a7a',
        md5ext: 'f84989feee2cf462a1c597169777ee3c.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/f84989feee2cf462a1c597169777ee3c.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/f84989feee2cf462a1c597169777ee3c.png/get/'),
        tags: ['outdoors'],
    },
    {
        name: 'Castle 1',
        color: '#4a4a5a',
        md5ext: 'e1914ed7917267f1c2ef2b48004cade9.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/e1914ed7917267f1c2ef2b48004cade9.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/e1914ed7917267f1c2ef2b48004cade9.png/get/'),
        tags: ['castle'],
    },
    {
        name: 'Soccer',
        color: '#3a7a3a',
        md5ext: '04a63154f04b09494354090f7cc2f1b9.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/04a63154f04b09494354090f7cc2f1b9.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/04a63154f04b09494354090f7cc2f1b9.png/get/'),
        tags: ['sports', 'outdoors'],
    },
    {
        name: 'Galaxy',
        color: '#111111',
        md5ext: '5fab1922f254ae9fd150162c3e392bef.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/5fab1922f254ae9fd150162c3e392bef.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/5fab1922f254ae9fd150162c3e392bef.png/get/'),
        tags: ['space'],
    },
    {
        name: 'Theater',
        color: '#2a1a3a',
        md5ext: 'c2b097bc5cdb6a14ef5485202bc5ee76.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/c2b097bc5cdb6a14ef5485202bc5ee76.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/c2b097bc5cdb6a14ef5485202bc5ee76.png/get/'),
        tags: ['indoors', 'music'],
    },
    {
        name: 'Beach Malibu',
        color: '#c4b48a',
        md5ext: '050615fe992a00d6af0e664e497ebf53.png',
        url: 'https://assets.scratch.mit.edu/internalapi/asset/050615fe992a00d6af0e664e497ebf53.png/get/',
        img: createAssetImg('https://assets.scratch.mit.edu/internalapi/asset/050615fe992a00d6af0e664e497ebf53.png/get/'),
        tags: ['outdoors'],
    },
];