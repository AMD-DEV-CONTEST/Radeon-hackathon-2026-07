/**
 * Kido Dev Curated Asset Library
 *
 * Strategy: Instead of hardcoding md5ext hashes (which can change),
 * we store the *names* that match entries in the live Scratch CDN JSON.
 * AssetModal will filter the live library and show matching entries
 * under the "Kido Picks" category.
 *
 * Sounds are synthesized locally in soundEngine.js with no external fetch.
 */

// Names of sprites from the official Scratch sprite library to include in "Kido Picks"
export const KIDO_SPRITE_NAMES = [
    'Cat',          // Animals – 2 walking costumes
    'Dog1',         // Animals
    'Frog',         // Animals
    'Monkey',       // Animals
    'Butterfly 1',  // Animals – 2 wing costumes
    'Radio',        // Music / Objects
    'drum',         // Drums set
    'Drum',         // Alternate name
    'Balloon1',     // Objects
    'Apple',        // Food
    'Ghost',        // Fantasy
    'Tree',         // Nature
    'Bread',        // Food – closest to Banana in scratch
    'Bananas',      // Food
    'Banana',       // Food
];

// Exact names of backdrops from the official Scratch backdrop library
export const KIDO_BACKDROP_NAMES = [
    'Bedroom 1',
    'Bedroom 2',
    'Jungle',
    'Safari',
];

// Sounds: these are purely synthesized in soundEngine.js
// Listed here so AssetModal can show them as Kido Dev's built-in sounds
export const KIDO_SOUNDS = [
    { name: 'Dance Music', tags: ['loops', 'kido picks'], id: 'dance', md5ext: null },
    { name: 'Meow', tags: ['animals', 'kido picks'], id: 'meow', md5ext: null },
    { name: 'Bark', tags: ['animals', 'kido picks'], id: 'bark', md5ext: null },
    { name: 'Croak', tags: ['animals', 'kido picks'], id: 'croak', md5ext: null },
    { name: 'Chomp', tags: ['food', 'kido picks'], id: 'chomp', md5ext: null },
    { name: 'Pop', tags: ['effects', 'kido picks'], id: 'pop', md5ext: null },
    { name: 'Jungle', tags: ['nature', 'kido picks'], id: 'jungle', md5ext: null },
];

// White Stage as a local colour-fill backdrop (no CDN needed)
export const WHITE_STAGE_BACKDROP = {
    name: 'White Stage',
    color: '#FFFFFF',
    emoji: '⬜',
    isLocal: true,
};
