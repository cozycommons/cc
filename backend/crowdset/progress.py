"""Read bounded FFmpeg telemetry without interrupting the rendering process."""
import json
import math
import re


def snapshot(directory):
    try:
        data = json.loads((directory / 'progress.json').read_text())
    except (OSError, ValueError):
        return {}
    result = {key: data[key] for key in ('stage', 'processing') if key in data}
    render = data.get('render')
    if not render:
        return result
    path = (directory / render['file']).resolve()
    if not path.is_relative_to(directory.resolve()):
        return result
    try:
        with path.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 8192))
            text = stream.read(8192).decode('utf-8', errors='replace')
        records = re.findall(r'frame=(\d+)\nfps=([\d.]+)\n.*?progress=(?:continue|end)\n', text, re.DOTALL)
        if not records:
            return result
        frames, fps = int(records[-1][0]), float(records[-1][1])
        completed = render['completed_frames'] + min(frames, render['segment_frames'])
        total = render['total_frames']
        if total <= 0:
            return result
        result['processing'].update(completed=completed, total=total, unit='frames',
                                    percent=min(100, math.floor(completed / total * 100)),
                                    updated_at=path.stat().st_mtime)
        if math.isfinite(fps) and fps > 0 and frames >= 120:
            result['processing']['remaining_seconds'] = math.ceil(max(0, total - completed) / fps)
    except (OSError, ValueError):
        pass
    return result
