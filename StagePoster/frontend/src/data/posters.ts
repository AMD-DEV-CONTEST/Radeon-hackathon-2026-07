// Mock data for the Landing "Poster Gallery / Visual Archive" section.
// Structured so it can later be replaced with a real API call — each entry
// carries enough metadata for filtering, theming, and analytics.

export type PosterCategory = 'live' | 'event' | 'music' | 'future';

export type PosterCase = {
  id: string;
  title: string;
  category: PosterCategory;
  categoryLabel: string;
  location: string;
  year: string;
  style: string;
  palette: [string, string, string]; // bg / mid / accent
  motif: 'duel' | 'solo' | 'crowd' | 'orbit' | 'grid' | 'wave';
  badge?: string;
  imageUrl?: string;
};

export const categoryFilters: { key: 'all' | PosterCategory; label: string; zh: string }[] = [
  { key: 'all',    label: 'All',    zh: '全部' },
  { key: 'live',   label: 'Live',   zh: '现场' },
  { key: 'event',  label: 'Event',  zh: '活动' },
  { key: 'music',  label: 'Music',  zh: '音乐' },
  { key: 'future', label: 'Future', zh: '未来' },
];

export const posters: PosterCase[] = [
  {
    id: 'changan-duel',
    title: "Chang'an Duel",
    category: 'live',
    categoryLabel: 'Metal Performance',
    location: "Xi'an",
    year: '2026',
    style: 'Qin Dynasty × Metal',
    palette: ['#1a0d08', '#3a1a10', '#C8603D'],
    motif: 'duel',
    badge: 'FLAGSHIP',
    imageUrl: '/gallery/changan-duel.png',
  },
  {
    id: 'cyber-live-night',
    title: 'Signal Through the Wall',
    category: 'event',
    categoryLabel: 'Electronic Event',
    location: "Xi'an",
    year: '2026',
    style: 'Industrial Live Collage',
    palette: ['#08080f', '#1a1238', '#7a5cff'],
    motif: 'grid',
    imageUrl: '/gallery/signal-wall.png',
  },
  {
    id: 'future-dimension',
    title: 'Neon Fault',
    category: 'future',
    categoryLabel: 'Music Festival',
    location: 'Shanghai',
    year: '2026',
    style: 'Damaged Digital Zine',
    palette: ['#05080f', '#0a2540', '#5cb6ff'],
    motif: 'orbit',
    imageUrl: '/gallery/neon-fault.png',
  },
  {
    id: 'neon-run',
    title: 'Neon Run',
    category: 'event',
    categoryLabel: 'City Marathon',
    location: 'Shenzhen',
    year: '2025',
    style: 'Synthwave',
    palette: ['#0a0512', '#3a0f4a', '#ff5ca8'],
    motif: 'wave',
  },
  {
    id: 'midnight-choir',
    title: 'Midnight Choir',
    category: 'music',
    categoryLabel: 'Live Concert',
    location: 'Chengdu',
    year: '2025',
    style: 'Cinematic',
    palette: ['#0b0810', '#2a1410', '#d4a05c'],
    motif: 'solo',
  },
  {
    id: 'quantum-bloom',
    title: 'Quantum Bloom',
    category: 'future',
    categoryLabel: 'Art Exhibition',
    location: 'Hangzhou',
    year: '2026',
    style: 'Bioluminescent',
    palette: ['#04080a', '#0c2a2a', '#7eb380'],
    motif: 'crowd',
  },
  {
    id: 'velvet-underground',
    title: 'Velvet Underground',
    category: 'live',
    categoryLabel: 'Jazz Night',
    location: 'Guangzhou',
    year: '2025',
    style: 'Editorial Noir',
    palette: ['#0d0a08', '#231a14', '#e0784f'],
    motif: 'solo',
  },
  {
    id: 'parallel-signal',
    title: 'Parallel Signal',
    category: 'music',
    categoryLabel: 'Indie Showcase',
    location: 'Tokyo',
    year: '2026',
    style: 'Analog Tape',
    palette: ['#0a0a0e', '#1c1d24', '#cdb892'],
    motif: 'grid',
  },
];
