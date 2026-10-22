from datetime import datetime

import numpy as np
import pytest

from crowdset.audio import align
from crowdset.timestamps import capture_metadata, hint_for, apply_hint


def test_capture_time_uses_container_timezone_and_ignores_stream_and_output_tags():
    report = '''Input #0, mov
    Metadata:
      creation_time : 2026-10-11T04:47:47Z
      com.apple.quicktime.creationdate: 2026-10-10T21:47:47-0700
      com.apple.quicktime.make: Apple
      com.apple.quicktime.model: iPhone 13 Pro Max
    Duration: 00:00:11.45
    Stream #0:0:
      creation_time: 2026-10-19T00:00:00Z
    Output #0:
      creation_time: 2026-10-20T00:00:00Z'''
    value = capture_metadata(report)
    assert value['at'] == datetime.fromisoformat('2026-10-11T04:47:47+00:00').timestamp()
    assert value['source'] == 'com.apple.quicktime.creationdate'
    assert value['camera'] == 'Apple iPhone 13 Pro Max'
    assert capture_metadata(report[report.index('    Stream #'):]) is None


@pytest.mark.parametrize('date', ['bad', '2026-10-11T04:47:47', '1904-01-01T00:00:00Z'])
def test_invalid_and_unzoned_capture_times_are_not_used(date):
    assert capture_metadata('creation_time: ' + date) is None


def peer(id, offset, *, at=None, uploader='u', camera='iPhone', assisted=False):
    return {'id': id, 'uploader': uploader,
            'capture': {'at': 1_000_000 + offset if at is None else at, 'camera': camera, 'source': 'creation_time'},
            'alignment': {'status': 'matched', 'offset_seconds': offset, 'timestamp_assisted': assisted}}


def test_clock_hint_needs_independent_consistent_peers_and_never_uses_target_itself():
    a, b, target = peer('a', 100), peer('b', 200), peer('target', 300)
    assert hint_for(target, [a, b, target], 'official')['offset_seconds'] == 300
    assert hint_for(target, [a, target], 'official') is None
    assert hint_for(target, [a, peer('b', 200, assisted=True)], 'official') is None
    assert hint_for(target, [a, peer('b', 200, uploader='other')], 'official') is None
    assert hint_for(target, [a, peer('b', 200, camera='Android')], 'official') is None
    assert hint_for(target, [a, peer('b', 200, at=1_003_800)], 'official') is None
    assert hint_for(target, [a, peer('b', 105)], 'official') is None
    assert hint_for(target, [a, b], 'a') is None
    assert hint_for({**target, 'source_url': 'https://youtu.be/example'}, [a, b], 'official') is None
    assert hint_for({**target, 'capture': None}, [a, b], 'official') is None
    assert hint_for(target, [peer('a', 100, at=1_000_000), peer('b', 200, at=1_000_000)], 'official') is None


def test_timestamp_resolves_duplicate_passage_only_with_distinct_audio_inside_hint():
    rng = np.random.default_rng(13)
    reference = rng.normal(size=(5000, 24)).astype(np.float32)
    query = reference[1000:1100].copy()
    reference[3000:3100] = query
    audio = align(reference, query)
    assert audio['status'] == 'unmatched' and audio['reason_code'] == 'ambiguous'
    hint = {'offset_seconds': 40, 'tolerance_seconds': 15, 'peer_ids': ['a', 'b']}
    matched = apply_hint(reference, query, audio, hint)
    assert matched['status'] == 'matched' and matched['timestamp_assisted']
    assert matched['offset_seconds'] == 40
    wrong = apply_hint(reference, query, audio, {**hint, 'offset_seconds': 80})
    assert wrong['status'] == 'unmatched'
    unrelated = rng.normal(size=query.shape)
    assert apply_hint(reference, unrelated, align(reference, unrelated), hint)['status'] == 'unmatched'
    reference[1200:1300] = query
    assert apply_hint(reference, query, align(reference, query), hint)['status'] == 'unmatched'


def test_timestamp_never_overrides_confident_audio_and_explains_outside_set():
    reference = np.random.default_rng(44).normal(size=(1000, 24)).astype(np.float32)
    query = reference[200:300]
    audio = align(reference, query)
    hint = {'offset_seconds': -600, 'tolerance_seconds': 15, 'peer_ids': ['a', 'b']}
    assert apply_hint(reference, query, audio, hint) == audio
    unmatched = align(reference, np.zeros_like(query))
    result = apply_hint(reference, query, unmatched, hint)
    assert result['status'] == 'unmatched' and 'outside this set' in result['reason']


def test_capture_cache_retries_failed_probe_and_newly_eligible_official(tmp_path, monkeypatch):
    from crowdset.worker import capture_clock
    from crowdset.limits import Limits
    from crowdset.storage import OriginalStore
    originals = OriginalStore(tmp_path)
    clip = {'id': 'phone', 'file': 'phone.mov'}
    source = originals.destination('set', clip)
    source.write_bytes(b'original bytes')
    analysis = {'version': 2, 'video': {'audio_start': 0}}
    calls = []
    def capture(path, limits):
        calls.append(path)
        if len(calls) == 1:
            raise ValueError('Temporary probe timeout')
        return {'at': 1_000_000, 'camera': 'iPhone', 'source': 'creation_time'}
    monkeypatch.setattr('crowdset.worker.video.capture', capture)
    data = {'id': 'set', 'soundtrack_clip_id': 'phone'}
    capture_clock(analysis, clip, data, originals, tmp_path, Limits())
    assert not calls and 'capture_version' not in analysis
    data['soundtrack_clip_id'] = None
    capture_clock(analysis, clip, data, originals, tmp_path, Limits())
    assert len(calls) == 1 and 'capture_version' not in analysis
    assert analysis['version'] == 2 and source.read_bytes() == b'original bytes'
    capture_clock(analysis, clip, data, originals, tmp_path, Limits())
    assert len(calls) == 2 and analysis['capture_version'] == 1
    capture_clock(analysis, clip, data, originals, tmp_path, Limits())
    assert len(calls) == 2


def test_short_noisy_clip_uses_calibrated_clock_without_claiming_audio_confidence():
    rng = np.random.default_rng(92)
    reference = rng.normal(size=(5000, 24)).astype(np.float32)
    source = rng.normal(size=(56, 24)).astype(np.float32)
    audio = align(reference, source)
    assert audio['status'] == 'unmatched'
    hint = {'offset_seconds': 40.3, 'tolerance_seconds': 15,
            'uncertainty_seconds': 2, 'peer_ids': ['a', 'b']}
    estimated = apply_hint(reference, source, audio, hint)
    assert estimated['status'] == 'matched'
    assert estimated['offset_seconds'] == 40.3
    assert estimated['match_method'] == 'timestamp'
    assert estimated['uncertainty_seconds'] == 2 and estimated['agreement'] == 0
    assert estimated['timestamp_assisted']
    assert apply_hint(reference, source, audio, None) == audio
    assert apply_hint(reference, np.zeros_like(source), audio, hint) == audio
    # Never turn a clip partly outside the recording into a timestamp-only insert.
    assert apply_hint(reference, source, audio, {**hint, 'offset_seconds': -.5}) == audio
    assert apply_hint(reference, source, audio, {**hint, 'offset_seconds': 199}) == audio


def test_guided_matching_can_abstain_on_a_noisy_section_but_not_a_conflicting_one():
    rng = np.random.default_rng(93)
    reference = rng.normal(size=(5000, 24)).astype(np.float32)
    source = reference[1000:1250].copy()
    source[166:] = rng.normal(size=(84, 24))
    original = align(reference, source)
    assert original['status'] == 'unmatched'
    hint = {'offset_seconds': 40, 'tolerance_seconds': 15, 'peer_ids': ['a', 'b']}
    matched = apply_hint(reference, source, original, hint)
    assert matched['status'] == 'matched' and matched['offset_seconds'] == 40
    assert matched['agreement'] == 2 and not matched['windows'][-1]['strong']
    # An actual edit to a different moment inside the search region must still fail.
    source[166:] = reference[1400:1484]
    edited = align(reference, source)
    assert apply_hint(reference, source, edited, hint)['status'] == 'unmatched'


def test_guided_long_clip_resolves_repeated_audio_without_relaxing_global_matching():
    rng = np.random.default_rng(94)
    reference = rng.normal(size=(10000, 24)).astype(np.float32)
    source = reference[1000:2000].copy()
    reference[7000:8000] = source
    original = align(reference, source)
    assert original['status'] == 'unmatched'
    hint = {'offset_seconds': 40, 'tolerance_seconds': 15, 'peer_ids': ['a', 'b']}
    matched = apply_hint(reference, source, original, hint)
    assert matched['status'] == 'matched' and matched['agreement'] == 3
    assert matched['offset_seconds'] == 40
    assert apply_hint(reference, source, original, {**hint, 'offset_seconds': 140}) == original
