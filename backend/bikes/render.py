"""A PNG map of live stations over the street basemap, for agents that can show images.

Chat agents (Muse, Dots, ChatGPT, Claude) can display an image or a link even
when they cannot run our page, so every answer carries `map_image` (this) and
`map_url` (the interactive page). Same tiles as the page (bikes.basemap), same
station colors. Renders at twice the size and downsamples for smooth edges.
"""
from functools import lru_cache
import io
import json
import math
from pathlib import Path
import threading

from cachetools import TTLCache
from PIL import Image, ImageChops, ImageDraw, ImageFont

MAP_DIR = Path(__file__).with_name('map')
M_PER_DEG = 111320
SIZE = 640
SCALE = 2  # drawn at SIZE * SCALE, then downsampled

PAPER = '#fffaf2'
WATER = '#cfe2f5'
PARK = '#dfe6cf'
STREETS = (('minor', '#e8dcc6', 1.6), ('major', '#d8c3a0', 3.2), ('bike', '#69755a', 1.2))
LEVELS = {'ok': '#0ca30c', 'low': '#fab219', 'out': '#d03b3b', 'closed': '#9a8f82'}
INK, INK_SOFT, YOU = '#3d2f29', '#6f6256', '#2a78d6'

_cache = TTLCache(maxsize=256, ttl=60)
_lock = threading.Lock()
# The route is public and each view is a fresh cache key, so cap concurrent
# renders rather than let a burst of distinct views take every API worker.
_renders = threading.BoundedSemaphore(2)


class Busy(Exception):
    """Every render slot is taken."""


@lru_cache(maxsize=1)
def index():
    return json.loads((MAP_DIR / 'index.json').read_text())


@lru_cache(maxsize=512)
def tile(key):
    path = MAP_DIR / f'{key}.json'
    return json.loads(path.read_text()) if path.exists() else {}


def lines_in(south, west, north, east):
    """{layer: [[(lng, lat), ...], ...]} for the tiles covering the box."""
    meta = index()
    lat0, lng0 = meta['origin']
    d_lat, d_lng = meta['tile']
    have, q = set(meta['tiles']), meta['quantum']
    out = {}
    for x in range(math.floor((west - lng0) / d_lng), math.floor((east - lng0) / d_lng) + 1):
        for y in range(math.floor((south - lat0) / d_lat), math.floor((north - lat0) / d_lat) + 1):
            if f'{x}_{y}' not in have:
                continue
            ox, oy = lng0 + x * d_lng, lat0 + y * d_lat
            for layer, polylines in tile(f'{x}_{y}').items():
                if layer == 'names':  # labels, not polylines
                    continue
                for flat in polylines:
                    qx = qy = 0
                    points = []
                    for i in range(0, len(flat), 2):
                        qx, qy = (qx + flat[i], qy + flat[i + 1]) if i else (flat[i], flat[i + 1])
                        points.append((ox + qx * q, oy + qy * q))
                    out.setdefault(layer, []).append(points)
    return out


def level(dock, need, now):
    if dock.stale(now):
        return 'closed'
    serving = dock.returning if need == 'dock' else dock.renting
    if not serving:
        return 'closed'
    count = dock.docks if need == 'dock' else dock.ebikes if need == 'ebike' else dock.bikes
    return 'ok' if count >= 3 else 'low' if count > 0 else 'out'


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow without sized default fonts
        return ImageFont.load_default()


def render(docks, now, lat, lng, radius_m, need='bike', marks=(), you=True, stamp=''):
    """PNG bytes: `radius_m` either side of (lat, lng)."""
    size = SIZE * SCALE
    k = math.cos(math.radians(lat))
    px_per_m = size / 2 / radius_m

    def xy(point):
        p_lng, p_lat = point
        return (size / 2 + (p_lng - lng) * M_PER_DEG * k * px_per_m,
                size / 2 - (p_lat - lat) * M_PER_DEG * px_per_m)

    d_lat = radius_m * 1.05 / M_PER_DEG
    d_lng = d_lat / k
    layers = lines_in(lat - d_lat, lng - d_lng, lat + d_lat, lng + d_lng)
    img = Image.new('RGB', (size, size), PAPER)

    # Water rings arrive clipped per tile; XOR keeps islands inside them as land.
    mask = Image.new('1', (size, size), 0)
    for ring in layers.get('sea', []) + layers.get('water', []):
        if len(ring) >= 3:
            one = Image.new('1', (size, size), 0)
            ImageDraw.Draw(one).polygon([xy(p) for p in ring], fill=1)
            mask = ImageChops.logical_xor(mask, one)
    img.paste(WATER, mask=mask)
    draw = ImageDraw.Draw(img)
    for ring in layers.get('park', []):
        if len(ring) >= 3:
            draw.polygon([xy(p) for p in ring], fill=PARK)
    for name, color, width in STREETS:
        for line in layers.get(name, []):
            draw.line([xy(p) for p in line], fill=color, width=max(1, round(width * SCALE * min(1.6, 800 / radius_m))),
                      joint='curve')

    label = font(11 * SCALE)
    visible = []
    for dock in docks:
        x, y = xy((dock.lng, dock.lat))
        if -20 <= x <= size + 20 and -20 <= y <= size + 20:
            visible.append((math.hypot(x - size / 2, y - size / 2), dock, x, y))
    visible.sort(key=lambda v: v[0])
    marked = set(marks)
    # Counts on the marked stations, and the nearest few when zoomed in, so the image answers on its own.
    labeled = {dock.short_name for i, (_, dock, _, _) in enumerate(visible)
               if dock.short_name in marked or (i < 6 and radius_m <= 1200)}
    dot = max(4, round(7 * min(1.0, 800 / radius_m))) * SCALE
    for _, dock, x, y in reversed(visible):
        color = LEVELS[level(dock, need, now)]
        r = 12 * SCALE if dock.short_name in labeled else dot
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color, outline=INK if dock.short_name in marked else PAPER,
                     width=2 * SCALE)
        if dock.short_name in labeled:
            count = dock.docks if need == 'dock' else dock.ebikes if need == 'ebike' else dock.bikes
            draw.text((x, y), str(count), fill='white', font=label, anchor='mm')
    if you:
        r = 7 * SCALE
        draw.ellipse((size / 2 - r, size / 2 - r, size / 2 + r, size / 2 + r), fill=YOU, outline=PAPER, width=3 * SCALE)

    noun = {'dock': 'open docks', 'ebike': 'e-bikes'}.get(need, 'bikes')
    small = font(11 * SCALE)
    band = 26 * SCALE
    draw.rectangle((0, size - band, size, size), fill=PAPER)
    x = 10 * SCALE
    # ASCII only: the default font has no en dash.
    for key, text in (('ok', f'3+ {noun}'), ('low', '1-2'), ('out', 'none'), ('closed', 'closed or stale')):
        draw.ellipse((x, size - band / 2 - 5 * SCALE, x + 10 * SCALE, size - band / 2 + 5 * SCALE), fill=LEVELS[key])
        draw.text((x + 14 * SCALE, size - band / 2), text, fill=INK_SOFT, font=small, anchor='lm')
        x += 14 * SCALE + draw.textlength(text, font=small) + 12 * SCALE
    draw.text((size - 10 * SCALE, size - band / 2), f'{stamp} · © OpenStreetMap contributors'.strip(' ·'),
              fill=INK_SOFT, font=small, anchor='rm')

    out = io.BytesIO()
    img.resize((SIZE, SIZE), Image.LANCZOS).save(out, format='PNG', optimize=True)
    return out.getvalue()


def cached_render(key, make):
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    if not _renders.acquire(blocking=False):
        raise Busy
    try:
        png = make()
    finally:
        _renders.release()
    with _lock:
        _cache[key] = png
    return png
