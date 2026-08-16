import subprocess
import json
import uuid


def _get_aspect_ratio(video_path: str) -> tuple[int, int]:
    result = subprocess.run(
        [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', '-select_streams', 'v:0', video_path,
        ],
        capture_output=True, check=True,
    )
    stream = json.loads(result.stdout)['streams'][0]
    return stream['width'], stream['height']


def build_captions(video_path: str, transcript: dict, words_per_chunk: int = None) -> list[dict]:
    width, height = _get_aspect_ratio(video_path)
    if words_per_chunk is None:
        words_per_chunk = 4 if height > width else 8

    words = transcript.get('words', [])
    assets = []
    for i in range(0, len(words), words_per_chunk):
        group = words[i: i + words_per_chunk]
        assets.append({
            'id': str(uuid.uuid4()),
            'type': 'caption',
            'source': 'whisper',
            'start': group[0]['start'],
            'end': group[-1]['end'],
            'layer': 1,
            'position': {'x': 0.5, 'y': 0.85, 'anchor': 'center'},
            'content': {
                'text': ' '.join(w['word'] for w in group),
                # Per-word timestamps, kept alongside the joined text so renderers that
                # want word-level highlighting (e.g. highlight_color) know exactly when
                # each word is "active"; renderers that don't care just use 'text'.
                'words': [{'word': w['word'], 'start': w['start'], 'end': w['end']} for w in group],
            },
            'style': {
                'font': 'Roboto',
                'font_size': 72,
                'font_weight': 'Bold',  # bold weight reads clearly without a background box
                'font_italic': False,
                'color': '#FFFFFF',
                'background': 'none',  # no box; depth comes from outline + drop shadow in the ASS style
            },
        })
    return assets
