import json
import logging
import os
import subprocess
import tempfile

from groq import Groq

logger = logging.getLogger(__name__)


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


def get_duration_seconds(video_path: str) -> float:
    """Read the container duration via ffprobe -show_format. Used at upload time to
    reject videos over the max length before we ever transcribe/caption them — a long
    video means a huge caption count, which can blow up the LLM's context in a single
    read_assets call (see pipeline/tools.py's _MAX_ASSETS_UNFILTERED)."""
    result = subprocess.run(
        [
            'ffprobe', '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            video_path,
        ],
        capture_output=True,
        check=True,
    )
    data = json.loads(result.stdout)
    return float(data['format']['duration'])


def transcription_available() -> bool:
    """Whether the Groq transcription backend is configured in this environment.
    Checked before registering transcribe_video as an agent tool and before adding
    its system-prompt guidance, so a missing/expired key fails fast (no LLM round-trip,
    no wasted ffmpeg extraction) instead of surfacing only after a failed API call."""
    return bool(os.environ.get("GROQ_API_KEY"))


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

    # Generic, non-revealing message for anything below — the real exception (auth
    # failure, rate limit, ffmpeg stderr, network error) is logged server-side only.
    # Surfacing raw exception text to the chat agent would leak backend config details
    # (e.g. "invalid API key") straight into a user-facing reply.
    unavailable_msg = "Transcription is temporarily unavailable. Please try again later."

    try:
        try:
            subprocess.run(
                ['ffmpeg', '-y', '-i', video_path, '-vn', '-ac', '1', '-ar', '16000', '-b:a', '32k', audio_path],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            logger.exception("ffmpeg audio extraction failed for %s", video_path)
            raise RuntimeError(unavailable_msg)

        try:
            with open(audio_path, 'rb') as f:
                result = client.audio.transcriptions.create(
                    file=f,
                    model='whisper-large-v3-turbo',
                    response_format='verbose_json',
                    timestamp_granularities=['word', 'segment'],
                    language='en',
                    temperature=0.0,
                )
        except Exception:
            logger.exception("Groq transcription request failed")
            raise RuntimeError(unavailable_msg)

        return result.model_dump()
    finally:
        os.unlink(audio_path)
