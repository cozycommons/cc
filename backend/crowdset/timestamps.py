"""Capture-clock hints calibrated by independent audio matches."""
from datetime import datetime
import re
import statistics


def capture_metadata(report):
    container = re.split(r'Duration:|Stream #|Output #', report, maxsplit=1)[0]
    tags = dict(re.findall(r'^\s*(com\.apple\.quicktime\.(?:creationdate|make|model)|creation_time)\s*:\s*(.+?)\s*$', container, re.MULTILINE))
    camera = ' '.join(tags.get('com.apple.quicktime.' + key, '').strip() for key in ('make', 'model')).strip()
    for key in ('com.apple.quicktime.creationdate', 'creation_time'):
        try:
            value = datetime.fromisoformat(tags[key].replace('Z', '+00:00'))
            if value.utcoffset() is not None and 2000 <= value.year <= 2100:
                return {'at': value.timestamp(), 'source': key, 'camera': camera[:160]}
        except (KeyError, ValueError, OverflowError):
            pass
    return None


def hint_for(clip, peers, anchor_id):
    capture = clip.get('capture')
    if not capture or not capture.get('camera') or not clip.get('uploader') or clip.get('source_url'):
        return None
    origins, offsets, ids = [], [], []
    for peer in peers:
        other, match = peer.get('capture'), peer.get('alignment', {})
        if (peer['id'] in (clip['id'], anchor_id) or peer.get('source_url') or not other
                or peer.get('uploader') != clip['uploader'] or other.get('camera') != capture['camera']
                or other.get('source') != capture['source'] or match.get('status') != 'matched'
                or match.get('timestamp_assisted')):
            continue
        offsets.append(match['offset_seconds'])
        origins.append(other['at'] - match['offset_seconds'])
        ids.append(peer['id'])
    # A camera model is not a device ID. Require corroborating clocks over distinct moments.
    if len(origins) < 2 or max(offsets) - min(offsets) < 30 or max(origins) - min(origins) > 4:
        return None
    return {'offset_seconds': capture['at'] - statistics.median(origins),
            'tolerance_seconds': 15, 'peer_ids': sorted(ids)}


def apply_hint(reference, source, alignment, hint):
    from .audio import FPS, align_short
    if alignment['status'] != 'unmatched' or not hint:
        return alignment
    predicted, tolerance = hint['offset_seconds'], hint['tolerance_seconds']
    if predicted + len(source) / FPS < -tolerance or predicted > len(reference) / FPS + tolerance:
        return {**alignment, 'timestamp_hint': hint,
                'reason': 'The video timestamp suggests this clip was recorded outside this set.'}
    if alignment.get('reason_code') != 'ambiguous':
        return alignment
    start = max(0, int((predicted - tolerance) * FPS))
    end = min(len(reference), int((predicted + len(source) / FPS + tolerance) * FPS))
    assisted = align_short(reference[start:end], source)
    if assisted['status'] != 'matched':
        return alignment
    assisted['offset_seconds'] = round(assisted['offset_seconds'] + start / FPS, 3)
    for window in assisted['windows']:
        window['offset_seconds'] = round(window['offset_seconds'] + start / FPS, 3)
    return {**assisted, 'timestamp_assisted': True, 'timestamp_hint': hint}
