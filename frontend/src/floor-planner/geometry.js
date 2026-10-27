export const SNAP_TOLERANCE_INCHES = 2;
export const MIN_ELEMENT_SIZE = 1;
export const MIN_ZOOM = 0.1;
export const MAX_ZOOM = 4;

export const createId = (prefix = 'element') => `${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
export const clampZoom = (zoom) => Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
export const roundInch = (value) => Math.round(value * 4) / 4;

export function formatInches(value, precision = 0) {
  const sign = value < 0 ? '−' : '';
  const inches = Math.abs(value);
  const feet = Math.floor(inches / 12);
  const remainder = inches - feet * 12;
  const shown = precision ? remainder.toFixed(precision) : Math.round(remainder).toString();
  return `${sign}${feet}′${shown}″`;
}

export function rotateVector(vector, degrees) {
  const radians = degrees * Math.PI / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  return { x: vector.x * cos - vector.y * sin, y: vector.x * sin + vector.y * cos };
}

export function lineEndpoints(element) {
  if (element.type === 'line') return [{ x: element.x1, y: element.y1 }, { x: element.x2, y: element.y2 }];
  const length = element.type === 'wall' ? element.length : element.width;
  const half = rotateVector({ x: length / 2, y: 0 }, element.rotation ?? 0);
  return [{ x: element.x - half.x, y: element.y - half.y }, { x: element.x + half.x, y: element.y + half.y }];
}

function rotatedRectBounds(x, y, width, height, rotation = 0) {
  const radians = rotation * Math.PI / 180;
  const visualWidth = Math.abs(width * Math.cos(radians)) + Math.abs(height * Math.sin(radians));
  const visualHeight = Math.abs(width * Math.sin(radians)) + Math.abs(height * Math.cos(radians));
  return { left: x - visualWidth / 2, right: x + visualWidth / 2, top: y - visualHeight / 2, bottom: y + visualHeight / 2, width: visualWidth, height: visualHeight, centerX: x, centerY: y };
}

export function elementBounds(element) {
  if (element.type === 'wall') return rotatedRectBounds(element.x, element.y, element.length, element.thickness, element.rotation);
  if (element.type === 'opening') return rotatedRectBounds(element.x, element.y, element.width, element.thickness, element.rotation);
  if (['furniture', 'rectangle', 'ellipse'].includes(element.type)) return rotatedRectBounds(element.x, element.y, element.width, element.height, element.rotation);
  if (element.type === 'line') {
    return { left: Math.min(element.x1, element.x2), right: Math.max(element.x1, element.x2), top: Math.min(element.y1, element.y2), bottom: Math.max(element.y1, element.y2), width: Math.abs(element.x2 - element.x1), height: Math.abs(element.y2 - element.y1), centerX: (element.x1 + element.x2) / 2, centerY: (element.y1 + element.y2) / 2 };
  }
  if (element.type === 'freehand') {
    const xs = element.points.map((point) => point.x);
    const ys = element.points.map((point) => point.y);
    const left = Math.min(...xs);
    const right = Math.max(...xs);
    const top = Math.min(...ys);
    const bottom = Math.max(...ys);
    return { left, right, top, bottom, width: right - left, height: bottom - top, centerX: (left + right) / 2, centerY: (top + bottom) / 2 };
  }
  return rotatedRectBounds(element.x ?? 0, element.y ?? 0, 1, 1, 0);
}

export function sceneBounds(elements) {
  if (!elements.length) return { left: -120, top: -120, right: 120, bottom: 120, width: 240, height: 240, centerX: 0, centerY: 0 };
  const bounds = elements.map(elementBounds);
  const left = Math.min(...bounds.map((item) => item.left));
  const right = Math.max(...bounds.map((item) => item.right));
  const top = Math.min(...bounds.map((item) => item.top));
  const bottom = Math.max(...bounds.map((item) => item.bottom));
  return { left, right, top, bottom, width: right - left, height: bottom - top, centerX: (left + right) / 2, centerY: (top + bottom) / 2 };
}

export function fitViewport(elements, width, height, padding = 48) {
  const bounds = sceneBounds(elements);
  const zoom = clampZoom(Math.min((width - padding * 2) / Math.max(bounds.width, 1), (height - padding * 2) / Math.max(bounds.height, 1)));
  return { zoom, x: width / 2 - bounds.centerX * zoom, y: height / 2 - bounds.centerY * zoom };
}

export const screenToWorld = (point, viewport) => ({ x: (point.x - viewport.x) / viewport.zoom, y: (point.y - viewport.y) / viewport.zoom });

function candidateAxes(elements, excludeId) {
  const xs = [];
  const ys = [];
  elements.forEach((element) => {
    if (element.id === excludeId) return;
    const bounds = elementBounds(element);
    xs.push(bounds.left, bounds.centerX, bounds.right);
    ys.push(bounds.top, bounds.centerY, bounds.bottom);
    if (['wall', 'opening', 'line'].includes(element.type)) {
      lineEndpoints(element).forEach((point) => { xs.push(point.x); ys.push(point.y); });
    }
  });
  return { xs, ys };
}

const nearestDelta = (values, candidates, tolerance) => {
  let best = null;
  values.forEach((value) => candidates.forEach((candidate) => {
    const delta = candidate - value;
    if (Math.abs(delta) <= tolerance && (best === null || Math.abs(delta) < Math.abs(best))) best = delta;
  }));
  return best ?? 0;
};

export function snapPoint(point, elements, excludeId, tolerance = SNAP_TOLERANCE_INCHES) {
  const { xs, ys } = candidateAxes(elements, excludeId);
  return { x: point.x + nearestDelta([point.x], xs, tolerance), y: point.y + nearestDelta([point.y], ys, tolerance) };
}

export function snapElement(element, elements, tolerance = SNAP_TOLERANCE_INCHES) {
  const bounds = elementBounds(element);
  const { xs, ys } = candidateAxes(elements, element.id);
  const dx = nearestDelta([bounds.left, bounds.centerX, bounds.right], xs, tolerance);
  const dy = nearestDelta([bounds.top, bounds.centerY, bounds.bottom], ys, tolerance);
  if (element.type === 'line') return { ...element, x1: element.x1 + dx, x2: element.x2 + dx, y1: element.y1 + dy, y2: element.y2 + dy };
  if (element.type === 'freehand') return { ...element, points: element.points.map((point) => ({ x: point.x + dx, y: point.y + dy })) };
  return { ...element, x: element.x + dx, y: element.y + dy };
}

export function moveElement(element, dx, dy) {
  if (element.type === 'line') return { ...element, x1: element.x1 + dx, x2: element.x2 + dx, y1: element.y1 + dy, y2: element.y2 + dy };
  if (element.type === 'freehand') return { ...element, points: element.points.map((point) => ({ x: point.x + dx, y: point.y + dy })) };
  return { ...element, x: element.x + dx, y: element.y + dy };
}

export function resizeRectFromCorner(element, corner, startPoint, point) {
  const localDelta = rotateVector({ x: point.x - startPoint.x, y: point.y - startPoint.y }, -(element.rotation ?? 0));
  const east = corner.includes('e');
  const south = corner.includes('s');
  const xSign = east ? 1 : -1;
  const ySign = south ? 1 : -1;
  const width = Math.max(MIN_ELEMENT_SIZE, element.width + xSign * localDelta.x);
  const height = Math.max(MIN_ELEMENT_SIZE, element.height + ySign * localDelta.y);
  const effectiveX = (width - element.width) / xSign;
  const effectiveY = (height - element.height) / ySign;
  const centerDelta = rotateVector({ x: effectiveX / 2, y: effectiveY / 2 }, element.rotation ?? 0);
  return { ...element, x: element.x + centerDelta.x, y: element.y + centerDelta.y, width: roundInch(width), height: roundInch(height) };
}

export function elementFromEndpoints(element, first, second) {
  const dx = second.x - first.x;
  const dy = second.y - first.y;
  const length = Math.max(MIN_ELEMENT_SIZE, Math.hypot(dx, dy));
  const rotation = Math.atan2(dy, dx) * 180 / Math.PI;
  if (element.type === 'line') return { ...element, x1: first.x, y1: first.y, x2: second.x, y2: second.y };
  return { ...element, x: (first.x + second.x) / 2, y: (first.y + second.y) / 2, rotation, [element.type === 'wall' ? 'length' : 'width']: roundInch(length) };
}
