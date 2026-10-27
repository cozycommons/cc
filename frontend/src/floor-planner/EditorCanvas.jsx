import { useEffect, useMemo, useRef, useState } from 'react';
import {
  clampZoom, createId, elementBounds, elementFromEndpoints, fitViewport,
  formatInches, lineEndpoints, moveElement, resizeRectFromCorner, rotateVector,
  roundInch, screenToWorld, snapElement, snapPoint,
} from './geometry';
import { FURNITURE_CATALOG } from './initialScene';

const RECT_TOOLS = new Set(['rectangle', 'ellipse']);
const LINE_TOOLS = new Set(['wall', 'door', 'window', 'line']);

function pointerPosition(event, svg) {
  const bounds = svg.getBoundingClientRect();
  return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
}

function createElement(tool, point) {
  if (tool === 'wall') return { id: createId('wall'), type: 'wall', x: point.x, y: point.y, length: 1, thickness: 4, rotation: 0 };
  if (tool === 'door' || tool === 'window') return { id: createId(tool), type: 'opening', kind: tool, x: point.x, y: point.y, width: 1, thickness: 4, rotation: 0 };
  if (tool === 'line') return { id: createId('line'), type: 'line', x1: point.x, y1: point.y, x2: point.x, y2: point.y };
  if (RECT_TOOLS.has(tool)) return { id: createId(tool), type: tool, x: point.x, y: point.y, width: 1, height: 1, rotation: 0 };
  if (tool === 'draw') return { id: createId('draw'), type: 'freehand', points: [point] };
  if (FURNITURE_CATALOG[tool]) return { id: createId(tool), type: 'furniture', furnitureType: tool, label: FURNITURE_CATALOG[tool].label, x: point.x, y: point.y, width: FURNITURE_CATALOG[tool].width, height: FURNITURE_CATALOG[tool].height, rotation: 0 };
  return null;
}

export default function EditorCanvas({ scene, setScene, tool, setTool, selectedId, setSelectedId, fitSignal, onTransactionStart, onTransactionEnd, onDeleteSelected, readOnly = false }) {
  const svgRef = useRef(null);
  const operation = useRef(null);
  const spaceDown = useRef(false);
  const pointers = useRef(new Map());
  const pinch = useRef(null);
  const [viewport, setViewport] = useState(scene.viewport ?? { x: 0, y: 0, zoom: 1 });
  const selected = scene.elements.find((element) => element.id === selectedId);

  const commitViewport = (next) => {
    setViewport(next);
    setScene((current) => ({ ...current, viewport: next }));
  };

  const fit = () => {
    const svg = svgRef.current;
    if (!svg) return;
    const bounds = svg.getBoundingClientRect();
    commitViewport(fitViewport(scene.elements, bounds.width, bounds.height, 52));
  };

  useEffect(() => { fit(); }, [fitSignal]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (scene.viewport) setViewport(scene.viewport);
    else requestAnimationFrame(fit);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const down = (event) => {
      if (event.code === 'Space') spaceDown.current = true;
      const target = event.target;
      const editingText = target instanceof HTMLElement && (target.matches('input, textarea, [contenteditable="true"]') || target.isContentEditable);
      if (!readOnly && !editingText && (event.key === 'Delete' || event.key === 'Backspace') && selectedId) onDeleteSelected();
      if (event.key === 'Escape') { setSelectedId(null); setTool('select'); }
    };
    const up = (event) => { if (event.code === 'Space') spaceDown.current = false; };
    window.addEventListener('keydown', down); window.addEventListener('keyup', up);
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); };
  }, [onDeleteSelected, readOnly, selectedId, setSelectedId, setTool]);

  const startPinch = () => {
    const [id1, id2] = pointers.current.keys();
    const p1 = pointers.current.get(id1);
    const p2 = pointers.current.get(id2);
    const distance = Math.max(1, Math.hypot(p2.x - p1.x, p2.y - p1.y));
    const midpoint = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 };
    pinch.current = { ids: [id1, id2], distance, viewport, anchorWorld: screenToWorld(midpoint, viewport) };
  };

  const begin = (event) => {
    const svg = svgRef.current;
    const screen = pointerPosition(event, svg);
    pointers.current.set(event.pointerId, screen);
    svg.setPointerCapture?.(event.pointerId);

    if (pointers.current.size >= 2) {
      if (operation.current && operation.current.kind !== 'pan') onTransactionEnd();
      operation.current = null;
      startPinch();
      return;
    }

    if (event.button !== 0 && event.button !== 1) return;
    const world = screenToWorld(screen, viewport);
    if (tool === 'hand' || event.button === 1 || spaceDown.current) {
      operation.current = { kind: 'pan', screen, viewport };
    } else if (tool === 'select') {
      operation.current = { kind: 'pan', screen, viewport, background: true, moved: false };
    } else if (!readOnly) {
      onTransactionStart();
      const first = LINE_TOOLS.has(tool) ? snapPoint(world, scene.elements) : world;
      const element = createElement(tool, first);
      if (!element) return;
      setScene((current) => ({ ...current, elements: [...current.elements, element] }));
      setSelectedId(element.id);
      operation.current = { kind: 'create', tool, id: element.id, first };
      if (FURNITURE_CATALOG[tool]) { operation.current = null; onTransactionEnd(); }
    }
  };

  const beginElement = (event, element) => {
    if (tool !== 'select') return;
    pointers.current.set(event.pointerId, pointerPosition(event, svgRef.current));
    svgRef.current.setPointerCapture?.(event.pointerId);
    if (pointers.current.size >= 2) { startPinch(); return; }
    event.stopPropagation();
    const screen = pointerPosition(event, svgRef.current);
    const world = screenToWorld(screen, viewport);
    setSelectedId(element.id);
    if (readOnly) return;
    onTransactionStart();
    operation.current = { kind: 'move', id: element.id, first: world, element };
  };

  const beginHandle = (event, element, handle) => {
    if (readOnly) return;
    pointers.current.set(event.pointerId, pointerPosition(event, svgRef.current));
    svgRef.current.setPointerCapture?.(event.pointerId);
    if (pointers.current.size >= 2) { startPinch(); return; }
    event.stopPropagation();
    const world = screenToWorld(pointerPosition(event, svgRef.current), viewport);
    operation.current = { kind: handle === 'rotate' ? 'rotate' : 'resize', handle, id: element.id, first: world, element };
  };

  const move = (event) => {
    const screen = pointerPosition(event, svgRef.current);
    if (pointers.current.has(event.pointerId)) pointers.current.set(event.pointerId, screen);

    if (pinch.current) {
      const [id1, id2] = pinch.current.ids;
      const p1 = pointers.current.get(id1);
      const p2 = pointers.current.get(id2);
      if (!p1 || !p2) return;
      const distance = Math.max(1, Math.hypot(p2.x - p1.x, p2.y - p1.y));
      const midpoint = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 };
      const zoom = clampZoom(pinch.current.viewport.zoom * (distance / pinch.current.distance));
      const anchor = pinch.current.anchorWorld;
      setViewport({ zoom, x: midpoint.x - anchor.x * zoom, y: midpoint.y - anchor.y * zoom });
      return;
    }

    const op = operation.current;
    if (!op) return;
    if (op.kind === 'pan') {
      if (op.background && !op.moved && Math.hypot(screen.x - op.screen.x, screen.y - op.screen.y) > 4) op.moved = true;
      setViewport({ ...op.viewport, x: op.viewport.x + screen.x - op.screen.x, y: op.viewport.y + screen.y - op.screen.y });
      return;
    }
    const world = screenToWorld(screen, viewport);
    setScene((current) => ({ ...current, elements: current.elements.map((element) => {
      if (element.id !== op.id) return element;
      if (op.kind === 'move') return snapElement(moveElement(op.element, world.x - op.first.x, world.y - op.first.y), current.elements);
      if (op.kind === 'rotate') {
        const bounds = elementBounds(op.element);
        const start = Math.atan2(op.first.y - bounds.centerY, op.first.x - bounds.centerX);
        const now = Math.atan2(world.y - bounds.centerY, world.x - bounds.centerX);
        return { ...op.element, rotation: Math.round(((op.element.rotation ?? 0) + (now - start) * 180 / Math.PI) / 5) * 5 };
      }
      if (op.kind === 'resize') {
        if (['furniture', 'rectangle', 'ellipse'].includes(element.type)) return resizeRectFromCorner(op.element, op.handle, op.first, world);
        const ends = lineEndpoints(op.element);
        const index = op.handle === 'start' ? 0 : 1;
        const snapped = snapPoint(world, current.elements, element.id);
        ends[index] = snapped;
        return elementFromEndpoints(op.element, ends[0], ends[1]);
      }
      if (op.kind === 'create') {
        if (op.tool === 'draw') return { ...element, points: [...element.points, world] };
        if (RECT_TOOLS.has(op.tool)) return { ...element, x: (op.first.x + world.x) / 2, y: (op.first.y + world.y) / 2, width: Math.max(1, Math.abs(world.x - op.first.x)), height: Math.max(1, Math.abs(world.y - op.first.y)) };
        return elementFromEndpoints(element, op.first, snapPoint(world, current.elements, element.id));
      }
      return element;
    }) }));
  };

  const end = (event) => {
    pointers.current.delete(event.pointerId);

    if (pinch.current) {
      if (pointers.current.size >= 2) { startPinch(); return; }
      pinch.current = null;
      commitViewport(viewport);
      if (pointers.current.size === 1) {
        const [id] = pointers.current.keys();
        operation.current = { kind: 'pan', screen: pointers.current.get(id), viewport };
      }
      return;
    }

    const op = operation.current;
    if (op?.kind === 'pan') {
      commitViewport(viewport);
      if (op.background && !op.moved) setSelectedId(null);
    }
    if (op && op.kind !== 'pan') onTransactionEnd();
    operation.current = null;
  };

  const wheel = (event) => {
    event.preventDefault();
    if (event.ctrlKey || event.metaKey) {
      const screen = pointerPosition(event, svgRef.current);
      const world = screenToWorld(screen, viewport);
      const zoom = clampZoom(viewport.zoom * Math.exp(-event.deltaY * 0.002));
      commitViewport({ zoom, x: screen.x - world.x * zoom, y: screen.y - world.y * zoom });
    } else commitViewport({ ...viewport, x: viewport.x - event.deltaX, y: viewport.y - event.deltaY });
  };

  const grid = useMemo(() => Math.max(6, 12 * viewport.zoom), [viewport.zoom]);
  return <svg ref={svgRef} className={`editor-canvas tool-${tool}`} onPointerDown={begin} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onWheel={wheel} aria-label="Floor plan drawing canvas">
    <defs><pattern id="inch-grid" width={grid} height={grid} patternUnits="userSpaceOnUse"><path d={`M ${grid} 0 L 0 0 0 ${grid}`} /></pattern></defs>
    <rect width="100%" height="100%" fill="url(#inch-grid)" />
    <g transform={`translate(${viewport.x} ${viewport.y}) scale(${viewport.zoom})`}>
      {scene.elements.map((element) => <Element key={element.id} element={element} selected={element.id === selectedId} zoom={viewport.zoom} onPointerDown={beginElement} onHandle={beginHandle} readOnly={readOnly} />)}
    </g>
  </svg>;
}

function Element({ element, selected, zoom, onPointerDown, onHandle, readOnly }) {
  const handleRadius = 6 / zoom;
  const common = { onPointerDown: (event) => onPointerDown(event, element), className: `plan-element ${selected ? 'selected' : ''}` };
  let shape;
  if (element.type === 'wall') shape = <rect {...common} x={-element.length / 2} y={-element.thickness / 2} width={element.length} height={element.thickness} transform={`translate(${element.x} ${element.y}) rotate(${element.rotation})`} />;
  else if (element.type === 'opening') shape = <g {...common} transform={`translate(${element.x} ${element.y}) rotate(${element.rotation})`}><rect className={`opening-cut ${element.kind}`} x={-element.width / 2} y={-Math.max(element.thickness, 6) / 2} width={element.width} height={Math.max(element.thickness, 6)} />{element.kind === 'window' && <><line className="window-line" x1={-element.width / 2} x2={element.width / 2} y1={-1.2} y2={-1.2} /><line className="window-line" x1={-element.width / 2} x2={element.width / 2} y1={1.2} y2={1.2} /></>}</g>;
  else if (element.type === 'line') shape = <line {...common} x1={element.x1} y1={element.y1} x2={element.x2} y2={element.y2} />;
  else if (element.type === 'freehand') shape = <polyline {...common} points={element.points.map((point) => `${point.x},${point.y}`).join(' ')} />;
  else if (element.type === 'ellipse') shape = <ellipse {...common} cx={element.x} cy={element.y} rx={element.width / 2} ry={element.height / 2} transform={`rotate(${element.rotation} ${element.x} ${element.y})`} />;
  else shape = <g {...common} transform={`translate(${element.x} ${element.y}) rotate(${element.rotation ?? 0})`}><rect className={element.type === 'furniture' ? 'furniture-shape' : ''} x={-element.width / 2} y={-element.height / 2} width={element.width} height={element.height} rx={element.type === 'furniture' ? 2 : 0} />{element.type === 'furniture' && <FurnitureGlyph type={element.furnitureType} width={element.width} height={element.height} />}</g>;
  return <g>{shape}{selected && <Selection element={element} radius={handleRadius} onHandle={onHandle} readOnly={readOnly} />}</g>;
}

function Selection({ element, radius, onHandle, readOnly }) {
  const bounds = elementBounds(element);
  const endpoints = ['wall', 'opening', 'line'].includes(element.type) ? lineEndpoints(element) : null;
  const handle = (point, name) => readOnly ? null : <circle key={name} className="selection-handle" cx={point.x} cy={point.y} r={radius} onPointerDown={(event) => onHandle(event, element, name)} />;
  if (endpoints) return <g className="selection-ui"><line className="selection-axis" x1={endpoints[0].x} y1={endpoints[0].y} x2={endpoints[1].x} y2={endpoints[1].y} />{handle(endpoints[0], 'start')}{handle(endpoints[1], 'end')}<text x={bounds.centerX} y={bounds.top - radius * 2}>{formatInches(element.type === 'wall' ? element.length : element.type === 'opening' ? element.width : Math.hypot(element.x2 - element.x1, element.y2 - element.y1))}</text></g>;
  if (!['furniture', 'rectangle', 'ellipse'].includes(element.type)) return null;
  const halfW = element.width / 2, halfH = element.height / 2;
  const corners = [['nw', -halfW, -halfH], ['ne', halfW, -halfH], ['se', halfW, halfH], ['sw', -halfW, halfH]];
  const points = corners.map(([name, x, y]) => ({ name, ...rotateVector({ x, y }, element.rotation ?? 0), cx: element.x, cy: element.y }));
  const rotate = rotateVector({ x: halfW + radius * 4, y: halfH + radius * 4 }, element.rotation ?? 0);
  return <g className="selection-ui"><rect className="selection-box" x={-halfW} y={-halfH} width={element.width} height={element.height} transform={`translate(${element.x} ${element.y}) rotate(${element.rotation ?? 0})`} />{points.map((point) => handle({ x: point.cx + point.x, y: point.cy + point.y }, point.name))}{handle({ x: element.x + rotate.x, y: element.y + rotate.y }, 'rotate')}<text x={bounds.centerX} y={bounds.top - radius * 2}>{formatInches(element.width)} × {formatInches(element.height)}</text></g>;
}

function FurnitureGlyph({ type, width, height }) {
  const stroke = Math.max(1, Math.min(width, height) * .025);
  if (type === 'bed') return <g className="furniture-detail" strokeWidth={stroke}><rect x={-width * .43} y={-height * .43} width={width * .86} height={height * .18} rx={2} /><rect x={-width * .38} y={-height * .18} width={width * .32} height={height * .2} rx={3} /><rect x={width * .06} y={-height * .18} width={width * .32} height={height * .2} rx={3} /><path d={`M${-width * .46} ${height * .12} Q0 ${height * .03} ${width * .46} ${height * .12}`} /></g>;
  if (type === 'chair') return <g className="furniture-detail" strokeWidth={stroke}><rect x={-width * .34} y={-height * .35} width={width * .68} height={height * .25} rx={3} /><circle cx="0" cy={height * .12} r={Math.min(width, height) * .28} /></g>;
  return <g className="furniture-detail" strokeWidth={stroke}><rect x={-width * .42} y={-height * .38} width={width * .84} height={height * .76} rx={2} /><line x1={-width * .35} y1={height * .22} x2={width * .35} y2={height * .22} /></g>;
}
