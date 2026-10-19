"""Bounded, single-video YouTube imports; runs without storage credentials."""
import json
import math
from pathlib import Path
import re
import resource
import sys
import time
from urllib.parse import parse_qs, urlsplit

from .worker import write_json


def canonical_url(value):
    try:
        url = urlsplit(value.strip())
        if url.scheme != 'https' or url.username or url.password or url.port not in (None, 443):
            raise ValueError
        if url.hostname == 'youtu.be':
            video_id = url.path.removeprefix('/')
        elif url.hostname in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
            if url.path == '/watch':
                ids = parse_qs(url.query).get('v', [])
                video_id = ids[0] if len(ids) == 1 else ''
            else:
                match = re.fullmatch(r'/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})/?', url.path)
                video_id = match[1] if match else ''
        else:
            raise ValueError
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            raise ValueError
        return f'https://www.youtube.com/watch?v={video_id}'
    except (ValueError, AttributeError):
        raise ValueError('Paste an HTTPS YouTube link to a single video, not a playlist or channel.') from None


def validate_info(info, url, duration_limit):
    duration = info.get('duration')
    if info.get('id') != url.rsplit('=', 1)[-1] or info.get('_type', 'video') != 'video':
        raise ValueError('This link must resolve to one YouTube video.')
    if info.get('live_status') not in (None, 'not_live', 'was_live') or info.get('is_live'):
        raise ValueError('Live or upcoming streams cannot be imported. Wait for the finished video.')
    if info.get('availability') not in (None, 'public', 'unlisted') or (info.get('age_limit') or 0) >= 18:
        raise ValueError('This video requires restricted access. Upload an available recording instead.')
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 1 <= duration <= duration_limit:
        raise ValueError(f'YouTube videos must be between 1 second and {duration_limit // 60} minutes.')


class QuietLogger:
    def debug(self, message):
        pass

    warning = error = debug


def download(directory, url, max_bytes, duration_limit):
    import imageio_ffmpeg
    import yt_dlp

    directory = Path(directory)
    resource.setrlimit(resource.RLIMIT_FSIZE, (max_bytes, max_bytes))
    last_progress = 0

    def progress(event):
        nonlocal last_progress
        if event.get('downloaded_bytes', 0) > max_bytes:
            raise ValueError('This video exceeds the recording size limit.')
        if time.monotonic() - last_progress < 1 and event['status'] != 'finished':
            return
        last_progress = time.monotonic()
        total = event.get('total_bytes') or event.get('total_bytes_estimate')
        percent = min(100, int(100 * event.get('downloaded_bytes', 0) / total)) if total else None
        stage = f'Downloading from YouTube · {percent}%…' if percent is not None else 'Downloading from YouTube…'
        write_json(directory / 'progress.json', {'stage': stage})

    options = {
        'noplaylist': True, 'allowed_extractors': ['youtube'], 'default_search': 'error',
        'format': 'bv[height<=720][ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[height<=720][ext=mp4]',
        'merge_output_format': 'mp4', 'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe(),
        'js_runtimes': {'node': {}}, 'remote_components': [], 'cachedir': False,
        'socket_timeout': 20, 'retries': 1, 'fragment_retries': 1, 'extractor_retries': 1,
        'concurrent_fragment_downloads': 1, 'skip_unavailable_fragments': False,
        'max_filesize': max_bytes, 'outtmpl': str(directory / 'source.%(ext)s'),
        'logger': QuietLogger(), 'quiet': True, 'no_warnings': True, 'noprogress': True,
        'progress_hooks': [progress], 'proxy': '', 'overwrites': True,
    }
    write_json(directory / 'progress.json', {'stage': 'Checking YouTube video…'})
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)
        validate_info(info, url, duration_limit)
        downloader.process_ie_result(info, download=True)
    source = directory / 'source.mp4'
    if not source.is_file() or not 0 < source.stat().st_size <= max_bytes:
        raise ValueError('YouTube did not provide a video within the recording size limit.')
    title = re.sub(r'[\x00-\x1f\x7f/\\]', ' ', info.get('title') or 'YouTube video').strip()[:160]
    write_json(directory / 'result.json', {'name': f'{title}.mp4'})


if __name__ == '__main__':
    folder, source_url, size, seconds = sys.argv[1:]
    try:
        download(folder, canonical_url(source_url), int(size), int(seconds))
    except Exception as exc:
        # Downloader diagnostics can contain signed media URLs; expose only our validation errors.
        message = str(exc) if type(exc) is ValueError else 'YouTube could not provide this video to the server. It may be unavailable or blocking downloads. Try again later or upload the file.'
        write_json(Path(folder) / 'failure.json', {'error': message})
        sys.exit(1)
