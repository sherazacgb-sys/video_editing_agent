import json
import os
import subprocess
import tempfile

from groq import Groq


def _has_audio_stream(video_path: str) -> bool:
    # Ask ffprobe to list audio streams; an empty result means video-only.
    result = subprocess.run(
        [
            'ffprobe', '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            '-select_streams', 'a',  # audio streams only
            video_path,
        ],
        capture_output=True,
        check=True,
    )
    data = json.loads(result.stdout)
    return bool(data.get('streams'))  # empty list → no audio


def transcribe(video_path: str) -> dict:
    """Extract audio from video and transcribe it via Groq Whisper API."""
    # Fail fast with a clear message rather than letting ffmpeg crash with an
    # opaque exit code — video-only files (e.g. yt-dlp f401 streams) have no
    # audio track to extract.
    if not _has_audio_stream(video_path):
        raise ValueError(
            f"The video file has no audio track and cannot be transcribed. "
            f"If you downloaded this with yt-dlp, re-download with a format "
            f"that includes audio (e.g. yt-dlp -f 'bv*+ba/b' <url>)."
        )

    client = Groq()

    # MP3 at 32kbps mono keeps a 28-minute file under 7 MB, well within Groq's
    # 25 MB limit. WAV at 16kHz mono ran ~54 MB for the same duration and caused
    # 413 errors. Speech intelligibility is unaffected — Whisper was trained on
    # compressed internet audio and the 16kHz sample rate already caps useful
    # frequency content at 8 kHz regardless of container format.
    tmp_fd, audio_path = tempfile.mkstemp(suffix='.mp3')
    os.close(tmp_fd)

    try:
        subprocess.run(
            ['ffmpeg', '-y', '-i', video_path, '-vn', '-ac', '1', '-ar', '16000', '-b:a', '32k', audio_path],
            check=True,
            capture_output=True,
        )

        with open(audio_path, 'rb') as f:
            result = client.audio.transcriptions.create(
                file=f,
                model='whisper-large-v3-turbo',
                response_format='verbose_json',
                timestamp_granularities=['word', 'segment'],
                language='en',
                temperature=0.0,
            )

        return result.model_dump()
    finally:
        os.unlink(audio_path)
