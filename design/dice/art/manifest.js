// Reserved slots for the cozy farm/nature art (scenery + a handful of
// star characters). Drop finished images into this folder
// (e.g. `frontend/src/design/art/farmhouse-dusk.png`), import them below,
// and set `src` on the matching entry — the ArtGallery section picks it
// up automatically and swaps the placeholder window for the real image.
//
// import farmhouseDusk from './farmhouse-dusk.png';

export const SCENERY = [
  { key: 'farmhouse', label: 'Farmhouse at dusk', sublabel: 'lantern glow, cedar roof', mood: 'dusk', icon: 'house', aspect: '4 / 3', src: null },
  { key: 'road', label: 'Village road', sublabel: 'signpost, fences', mood: 'sky', icon: 'road', aspect: '4 / 3', src: null },
  { key: 'orchard', label: 'Orchard & tree line', sublabel: 'blossom trees', mood: 'blossom', icon: 'trees', aspect: '4 / 3', src: null },
  { key: 'field', label: 'Wheat field', sublabel: 'golden hour', mood: 'dusk', icon: 'wheat', aspect: '4 / 3', src: null },
  { key: 'hills', label: 'Rolling hills', sublabel: 'quiet countryside', mood: 'meadow', icon: 'hills', aspect: '4 / 3', src: null },
  { key: 'night-sky', label: 'Farm at night', sublabel: 'stars over the barn', mood: 'night', icon: 'sun', aspect: '4 / 3', src: null },
];

export const CHARACTERS = [
  { key: 'farmer', label: 'Farmer', sublabel: 'the player character', mood: 'meadow', icon: 'person', aspect: '3 / 4', src: null },
  { key: 'dog', label: 'Dog companion', sublabel: 'farm dog', mood: 'dusk', icon: 'dog', aspect: '3 / 4', src: null },
  { key: 'creature', label: 'Pixel creature', sublabel: 'small companion critter', mood: 'sky', icon: 'creature', aspect: '3 / 4', src: null },
  { key: 'neighbor', label: 'Neighbor', sublabel: 'a second character', mood: 'blossom', icon: 'person', aspect: '3 / 4', src: null },
];
