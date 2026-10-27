import floorplan from './floorplan.json';
import referenceSvg from './floorplan-reference.svg?raw';

export const SCENE_VERSION = 2;

const SVG_UNITS_PER_INCH = 2.54;

function svgGeometry(id) {
  const match = referenceSvg.match(new RegExp(`<rect\\s+id="${id}"[^>]*\\/>`));
  if (!match) return null;
  const attribute = (name) => Number(match[0].match(new RegExp(`${name}="([^"]+)"`))?.[1]);
  const x = attribute('x');
  const y = attribute('y');
  const width = attribute('width');
  const height = attribute('height');
  const rotation = Number(match[0].match(/transform="rotate\(([-\d.]+)/)?.[1] ?? 0);
  return { x: (x + width / 2) / SVG_UNITS_PER_INCH, y: (y + height / 2) / SVG_UNITS_PER_INCH, width: width / SVG_UNITS_PER_INCH, height: height / SVG_UNITS_PER_INCH, rotation };
}

const normalizeOpening = (opening, wall, room, kind) => {
  const exact = svgGeometry(opening.id);
  return ({
  id: opening.id,
  sourceId: opening.id,
  roomId: room.id,
  hostWallId: wall.id,
  type: 'opening',
  kind,
  x: exact?.x ?? opening.x,
  y: exact?.y ?? opening.z,
  width: exact?.width ?? opening.width,
  thickness: exact?.height ?? (opening.depth || wall.depth || 4),
  height: opening.height,
  rotation: exact?.rotation ?? opening.rotation ?? wall.rotation ?? 0,
  locked: false,
  });
};

export function normalizeFloorPlan(source = floorplan) {
  const elements = [];

  source.rooms.forEach((room, roomIndex) => {
    room.walls.forEach((wall) => {
      const exact = svgGeometry(wall.id);
      elements.push({
        id: wall.id,
        sourceId: wall.id,
        roomId: room.id,
        type: 'wall',
        x: exact?.x ?? wall.x,
        y: exact?.y ?? wall.z,
        length: exact?.width ?? wall.width,
        thickness: exact?.height ?? (wall.depth || 4),
        height: wall.height,
        rotation: exact?.rotation ?? wall.rotation ?? 0,
        locked: false,
      });
      wall.doors?.forEach((door) => elements.push(normalizeOpening(door, wall, room, 'door')));
      wall.windows?.forEach((window) => elements.push(normalizeOpening(window, wall, room, 'window')));
      wall.openings?.forEach((opening) => elements.push(normalizeOpening(opening, wall, room, 'opening')));
    });

    room.furniture_objects?.forEach((item) => {
      const exact = svgGeometry(item.id);
      elements.push({
        id: item.id,
        sourceId: item.id,
        roomId: room.id,
        type: 'furniture',
        furnitureType: item.category.toLowerCase(),
        label: item.category,
        x: exact?.x ?? item.x,
        y: exact?.y ?? item.z,
        width: exact?.width ?? item.width,
        height: exact?.height ?? item.depth,
        elevation: item.y,
        objectHeight: item.height,
        rotation: exact?.rotation ?? item.rotation ?? 0,
        locked: false,
      });
    });

    if (!room.name) room.name = `Room ${roomIndex + 1}`;
  });

  return {
    version: SCENE_VERSION,
    title: 'Apartment',
    units: 'inches',
    rooms: source.rooms.map((room, index) => ({ id: room.id, name: room.name || `Room ${index + 1}` })),
    elements,
    viewport: null,
  };
}

export const INITIAL_SCENE = normalizeFloorPlan();

export const createInitialScene = () => JSON.parse(JSON.stringify(INITIAL_SCENE));

export const FURNITURE_CATALOG = {
  bed: { label: 'Queen bed', width: 60, height: 80 },
  desk: { label: 'Desk', width: 55, height: 55 },
  chair: { label: 'Chair', width: 27, height: 27 },
};
