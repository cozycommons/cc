import wave

import numpy as np
import pytest
from scipy.signal import lfilter
from scipy.io import wavfile

from crowd_set.audio import RATE, align, decode, features, plan_timeline, render


def write_wav(path, values, rate=16000):
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        output.writeframes(np.clip(values, -32768, 32767).astype('<i2').tobytes())
    return path


def music(seconds=100, seed=1):
    rng = np.random.default_rng(seed)
    rate = 16000
    result = np.zeros(seconds * rate)
    for start in range(0, len(result), 3200):
        length = min(3200, len(result) - start)
        t = np.arange(length) / rate
        notes = rng.choice(np.arange(90, 4000, 37), 4, replace=False)
        phrase = sum(np.sin(2 * np.pi * note * t + rng.uniform(0, 6)) for note in notes)
        result[start:start + length] = phrase * np.hanning(length) * rng.uniform(800, 2500)
    return result


@pytest.fixture(scope='module')
def signal():
    return music()


def test_offset_with_tonal_change_and_noise(tmp_path, signal):
    ref = features(write_wav(tmp_path / 'ref.wav', signal))
    transformed = lfilter([.5, .3, .2], [1], signal[20 * 16000:70 * 16000])
    transformed += np.random.default_rng(3).normal(0, 200, len(transformed))
    match = align(ref, features(write_wav(tmp_path / 'clip.wav', transformed)))
    assert match['status'] == 'matched'
    assert match['offset_seconds'] == pytest.approx(20, abs=.04)
    assert match['agreement'] >= 3


def test_negative_offset_and_partial_overlap(tmp_path, signal):
    ref = features(write_wav(tmp_path / 'ref.wav', signal[20 * 16000:]))
    source = features(write_wav(tmp_path / 'source.wav', signal))
    match = align(ref, source)
    assert match['status'] == 'matched'
    assert match['offset_seconds'] == pytest.approx(-20, abs=.04)


def test_reject_unrelated_silence_short_and_edited(tmp_path, signal):
    ref = features(write_wav(tmp_path / 'ref.wav', signal))
    sources = [music(50, 99), np.zeros(50 * 16000), signal[:10 * 16000],
               np.concatenate((signal[10 * 16000:40 * 16000], signal[60 * 16000:90 * 16000]))]
    for index, source in enumerate(sources):
        result = align(ref, features(write_wav(tmp_path / f'source-{index}.wav', source)))
        assert result['status'] == 'unmatched', result


def test_nonoverlap_and_repeated_music_abstain(tmp_path, signal):
    ref = features(write_wav(tmp_path / 'ref.wav', signal[:45 * 16000]))
    source = features(write_wav(tmp_path / 'source.wav', signal[50 * 16000:]))
    assert align(ref, source)['status'] == 'unmatched'
    repeated = np.tile(signal[:20 * 16000], 5)
    ref = features(write_wav(tmp_path / 'repeat.wav', repeated))
    source = features(write_wav(tmp_path / 'repeated-clip.wav', repeated[5 * 16000:55 * 16000]))
    assert align(ref, source)['status'] == 'unmatched'


def clip(id, offset, duration, **extras):
    return {'id': id, 'role': 'crowd', 'included': True, 'duration': duration,
            'alignment': {'status': 'matched', 'offset_seconds': offset}, **extras}


def test_assembly_preserves_gaps_overlap_duration_and_reference_exclusion(tmp_path):
    clips = [clip('a', 2, 4), clip('b', 4, 5), clip('c', 10, 1),
             clip('reference', 0, 12, role='reference'), clip('disabled', 0, 12, included=False)]
    timeline = plan_timeline(clips, 12)
    assert timeline['gaps'] == [{'start': 0, 'end': 2}, {'start': 9, 'end': 10}, {'start': 11, 'end': 12}]
    assert [s['clip_id'] for s in timeline['segments']] == ['a', 'b', 'c']
    assert timeline['segments'][1]['fade_in'] == .08
    assert timeline['segments'][2]['fade_in'] == 0
    sources = {c['id']: write_wav(tmp_path / f'{c["id"]}.wav', np.full(round(c['duration'] * RATE), value), RATE)
               for c, value in zip(clips[:3], (1000, 3000, 5000))}
    assert render(timeline, sources, tmp_path / 'out.wav')
    with wave.open(str(tmp_path / 'out.wav')) as output:
        result = np.frombuffer(output.readframes(output.getnframes()), dtype='<i2')
    assert len(result) == 12 * RATE
    for lo, hi in ((0, 2), (9, 10), (11, 12)):
        assert np.all(result[lo * RATE:hi * RATE] == 0)
    assert result[int(5.96 * RATE)] == pytest.approx(2000, abs=2)
    assert result[int(6.1 * RATE)] == 3000
    assert result[int(10.1 * RATE)] == 5000


def test_bounds_and_no_matches(tmp_path):
    timeline = plan_timeline([clip('a', -2, 4), clip('b', 2, 8)], 5)
    assert timeline['segments'][0]['start'] == 0
    assert timeline['segments'][-1]['end'] == 5
    assert timeline['segments'][-1]['fade_in'] == 0
    empty = plan_timeline([clip('reference', 0, 20, role='reference')], 20)
    assert not render(empty, {}, tmp_path / 'empty.wav')
    assert not (tmp_path / 'empty.wav').exists()


def test_decode_rejects_invalid_media_and_limits(tmp_path, monkeypatch):
    bad = tmp_path / 'bad.mp3'
    bad.write_text('not media')
    with pytest.raises(ValueError, match='Cannot decode'):
        decode(bad, tmp_path / 'bad.wav')
    source = write_wav(tmp_path / 'source.wav', np.zeros(16000 * 2))
    assert decode(source, tmp_path / 'decoded.wav') == pytest.approx(2)
    rate, values = wavfile.read(tmp_path / 'decoded.wav')
    assert rate == RATE
    assert values.dtype == np.float32
    import subprocess
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('ffmpeg', 180)
    monkeypatch.setattr('crowd_set.audio.subprocess.run', timeout)
    with pytest.raises(ValueError, match='3 minute'):
        decode(source, tmp_path / 'timeout.wav')


def test_static_overlap_gain_matches_levels_preserves_dynamics_and_headroom(tmp_path, signal):
    from crowd_set.audio import loudness, match_levels
    a = signal[:60 * 16000]
    b = signal[40 * 16000:90 * 16000] * 2.5
    # Both source files are 32 kHz working audio, at deliberately different levels.
    sources = {'a': write_wav(tmp_path / 'a.wav', np.repeat(a, 2), RATE),
               'b': write_wav(tmp_path / 'b.wav', np.repeat(b, 2), RATE)}
    timeline = plan_timeline([clip('a', 0, 60), clip('b', 40, 50)], 90)
    levels = match_levels(timeline, sources)
    assert 'overlapping passage' in levels['b']['basis']
    assert levels['b']['gain_db'] - levels['a']['gain_db'] == pytest.approx(-20 * np.log10(2.5), abs=.15)
    assert all(level['estimated_true_peak_dbfs'] <= -1.99 for level in levels.values())
    render(timeline, sources, tmp_path / 'matched.wav')
    assert loudness(tmp_path / 'matched.wav')['true_peak_dbfs'] <= -1.9
    with wave.open(str(tmp_path / 'matched.wav')) as output:
        result = np.frombuffer(output.readframes(output.getnframes()), dtype='<i2')
    for key, lo, hi, original in [('a', 10, 20, np.repeat(a, 2)[10 * RATE:20 * RATE]),
                                   ('b', 70, 80, np.repeat(b, 2)[30 * RATE:40 * RATE])]:
        expected = original.astype('<i2').astype(float) * 10 ** (levels[key]['gain_db'] / 20)
        assert np.max(np.abs(result[lo * RATE:hi * RATE] - expected)) <= .501


def test_peak_headroom_uses_common_attenuation_and_discloses_fallback(tmp_path, monkeypatch):
    from crowd_set.audio import match_levels
    timeline = plan_timeline([clip('a', 0, 10), clip('b', 12, 10)], 22)
    monkeypatch.setattr('crowd_set.audio.loudness', lambda *args: {'integrated_lufs': -35, 'true_peak_dbfs': -1})
    levels = match_levels(timeline, {'a': tmp_path / 'a.wav', 'b': tmp_path / 'b.wav'})
    assert timeline['common_attenuation_db'] == 13
    assert levels['a']['gain_db'] == levels['b']['gain_db'] == -1
    assert 'fallback' in levels['b']['basis']


def test_extracts_audio_from_video_without_using_video_frames(tmp_path):
    import imageio_ffmpeg
    import subprocess
    source = write_wav(tmp_path / 'source.wav', music(2))
    video = tmp_path / 'phone.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error', '-y',
                    '-f', 'lavfi', '-i', 'color=c=black:s=32x32:r=1', '-i', str(source),
                    '-t', '2', '-c:v', 'libx264', '-c:a', 'aac', str(video)], check=True, timeout=20)
    duration = decode(video, tmp_path / 'working.wav')
    assert duration == pytest.approx(2, abs=.05)
    rate, values = wavfile.read(tmp_path / 'working.wav')
    assert values.ndim == 1
    assert rate == RATE
    assert values.std() > 100 / 32768


def test_decode_preserves_over_full_scale_peaks_until_final_gain(tmp_path):
    from crowd_set.audio import loudness, match_levels
    t = np.arange(12 * RATE) / RATE
    values = (1.4 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    source, working, output = [tmp_path / name for name in ('original.wav', 'working.wav', 'output.wav')]
    wavfile.write(source, RATE, values)
    assert decode(source, working) == 12
    rate, decoded = wavfile.read(working)
    assert rate == RATE
    assert np.max(np.abs(decoded)) > 1.39
    np.testing.assert_allclose(decoded, values, atol=1e-6)
    timeline = plan_timeline([clip('a', 0, 12)], 12)
    levels = match_levels(timeline, {'a': working})
    render(timeline, {'a': working}, output)
    _, rendered = wavfile.read(output)
    expected = values.astype(float) * 32768 * 10 ** (levels['a']['gain_db'] / 20)
    assert np.max(np.abs(rendered - expected)) <= .501
    assert loudness(output)['true_peak_dbfs'] <= -1.9
