"""Capture-clock hints calibrated by independent audio matches."""
from datetime import datetime
import re
import statistics

import numpy as np


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
            'tolerance_seconds': 15, 'uncertainty_seconds': max(1, max(origins) - min(origins) + 1),
            'peer_ids': sorted(ids)}


def apply_hint(reference, source, alignment, hint):
    from .audio import FPS, short_scores
    if alignment['status'] != 'unmatched' or not hint:
        return alignment
    predicted, tolerance = hint['offset_seconds'], hint['tolerance_seconds']
    if predicted + len(source) / FPS < -tolerance or predicted > len(reference) / FPS + tolerance:
        return {**alignment, 'timestamp_hint': hint,
                'reason': 'The video timestamp suggests this clip was recorded outside this set.'}
    if len(source) < FPS or len(source) > len(reference) or np.linalg.norm(source) < 1:
        return alignment
    first = max(0, int(np.ceil((predicted - tolerance) * FPS)))
    last = min(len(reference) - len(source), int(np.floor((predicted + tolerance) * FPS)))
    if last < first:
        return alignment

    def peak(start, end):
        # Every section competes over the same possible clip-start offsets.
        scores = short_scores(reference[first + start:last + end], source[start:end])
        best = int(np.argmax(scores))
        others = scores.copy()
        others[max(0, best - 6):best + 7] = -1
        return (first + best) / FPS, float(scores[best]), float(scores[best] - np.max(others))

    offset, score, margin = peak(0, len(source))
    boundaries = np.linspace(0, len(source), 4 if len(source) >= 6 * FPS else 3).astype(int)
    windows = []
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        position, similarity, separation = peak(start, end)
        windows.append({'source_seconds': round(int(start) / FPS, 3),
                        'duration_seconds': round(int(end - start) / FPS, 3),
                        'offset_seconds': round(position, 3), 'similarity': round(similarity, 4),
                        'peak_margin': round(separation, 4),
                        'strong': similarity >= 0.25 and separation >= 0.05})
    strong = [w for w in windows if w['strong']]
    agrees = [w for w in strong if abs(w['offset_seconds'] - offset) <= 0.16]
    if score >= 0.35 and margin >= 0.12 and len(agrees) >= 2 and len(agrees) == len(strong):
        spread = max(abs(w['offset_seconds'] - offset) for w in agrees)
        return {'status': 'matched', 'offset_seconds': round(offset, 3),
                'uncertainty_seconds': round(spread + 0.04, 3), 'similarity': round(score, 4),
                'peak_margin': round(margin, 4), 'agreement': len(agrees), 'windows': windows,
                'timestamp_assisted': True, 'timestamp_hint': hint,
                'reason': 'Audio sections agree near the calibrated video timestamp; listen to verify.'}
    # Very short phone clips may contain mostly crowd noise. Use the calibrated clock
    # explicitly as an estimate, rather than treating a noise peak as an audio match.
    if len(source) < 60 and 0 <= predicted <= (len(reference) - len(source)) / FPS:
        return {'status': 'matched', 'offset_seconds': round(predicted, 3),
                'uncertainty_seconds': round(hint.get('uncertainty_seconds', tolerance), 3),
                'agreement': 0, 'windows': windows, 'timestamp_assisted': True,
                'match_method': 'timestamp', 'timestamp_hint': hint,
                'reason': 'Too short for reliable audio matching; placed using the calibrated video timestamp. Timing is approximate.'}
    return alignment
