import uuid
from pathlib import Path

from langchain_core.tools import tool

from pipeline.captions import build_captions
from pipeline.transcribe import transcribe, transcription_available

# UI_MAP.md lives at the repo root (pipeline/tools.py -> pipeline/ -> repo root)
# and is tracked in git (unlike docs/) because read_ui_map reads it at runtime.
_UI_MAP_PATH = Path(__file__).resolve().parent.parent / "UI_MAP.md"

_HALIGN_X = {"left": 0.15, "center": 0.5, "right": 0.85}
_VALIGN_Y = {"top": 0.1, "middle": 0.5, "bottom": 0.85}

# Every name here must have a matching family bundled in static/fonts/bundled/
# (see pipeline/overlay.py's _FONTS_DIR) and loaded via @font-face in
# job_detail.html — otherwise the export and the browser preview would each
# silently fall back to a different substitute font.
_AVAILABLE_FONTS = [
    "Roboto", "Montserrat", "Oswald", "Gelasio", "Anton",
    # Bold/display/meme
    "Bebas Neue", "Archivo Black", "Bangers", "Alfa Slab One", "Luckiest Guy",
    # Script/casual/handwriting
    "Caveat", "Pacifico", "Dancing Script", "Permanent Marker", "Kalam",
    # Serif/editorial
    "Playfair Display", "Merriweather", "Lora", "Libre Baskerville",
    # Monospace/tech
    "JetBrains Mono", "Space Mono", "IBM Plex Mono", "Roboto Mono",
    # General sans
    "Inter", "Poppins",
]


def _validate_font(font: str) -> None:
    if font not in _AVAILABLE_FONTS:
        raise ValueError(f"Unknown font '{font}'. Available fonts: {', '.join(_AVAILABLE_FONTS)}.")


def _fmt_time(seconds) -> str:
    if seconds is None:
        return "?"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


# read_assets prints one line per asset with no pagination. Caption count scales with
# words_per_chunk (down to 1 word/caption for karaoke-style captions), so even a short,
# duration-capped video can produce thousands of assets — dumping all of them into a
# single tool result can blow past the LLM's context window in one call. Past this count,
# an unfiltered read_assets refuses and tells the agent to query a time window instead.
_MAX_ASSETS_UNFILTERED = 40


def make_tools(job_pk: int, video_path: str) -> list:
    @tool
    def transcribe_video() -> str:
        """Transcribe the uploaded video and extract word-level timestamps."""
        from videos.models import VideoJob
        result = transcribe(video_path)  # runs Whisper, returns dict with 'text', 'segments', 'words'
        j = VideoJob.objects.get(pk=job_pk)
        j.transcript = result
        j.stage = VideoJob.Stage.TRANSCRIBED
        j.save(update_fields=["transcript", "stage"])
        # Tell the agent the transcript is already readable in the UI so it points the user
        # there instead of immediately calling read_transcript to answer "what's this about".
        return (
            f"Transcription complete — {len(result.get('words', []))} words extracted. "
            f"The full transcript is now visible to the user in the Assets tab under \"Transcript\"."
        )

    @tool
    def read_transcript() -> str:
        """Return the full plain-text transcript of the video.
        The transcript is already visible to the user in the Assets tab under "Transcript" —
        for general questions like "what is this video about" or "what does it say", tell the
        user to look there instead of calling this tool.
        Only call this as a last resort when you need the actual transcript text yourself to
        solve a specific problem, e.g. checking a caption's wording/spelling against what was
        actually said, finding an exact quote or timestamp, or resolving an ambiguous word."""
        from videos.models import VideoJob
        j = VideoJob.objects.get(pk=job_pk)
        if not j.transcript:
            return "No transcript yet. Run transcribe_video first."
        text = j.transcript.get('text', '')  # plain-text transcript, same field the UI panel reads
        if not text:
            return "Transcript has no text content."
        return text

    @tool
    def generate_captions(words_per_chunk: int = None) -> str:
        """Generate timed caption chunks from the existing transcript and store them on the asset timeline.
        words_per_chunk controls how many words appear per caption (default: 4 for portrait, 8 for landscape).
        Pass words_per_chunk=1 for one-word-at-a-time karaoke-style captions.
        Any manually inserted text overlays (source='manual') are preserved."""
        from videos.models import VideoJob
        j = VideoJob.objects.get(pk=job_pk)
        if not j.transcript:
            return "No transcript yet. Run transcribe_video first."
        manual_assets = [a for a in (j.assets or []) if a.get('source') == 'manual']
        caption_assets = build_captions(video_path, j.transcript, words_per_chunk=words_per_chunk)
        j.assets = manual_assets + caption_assets
        j.stage = VideoJob.Stage.CAPTIONED
        j.save(update_fields=["assets", "stage"])
        kept = f" ({len(manual_assets)} manual overlay(s) preserved)" if manual_assets else ""
        chunk_note = f" ({words_per_chunk} word(s) per caption)" if words_per_chunk else ""
        return f"Generated {len(caption_assets)} caption chunks{chunk_note} and saved to asset timeline{kept}."

    @tool
    def read_assets(start: float = None, end: float = None) -> str:
        """Return all assets currently on the timeline, including their IDs.
        Optionally filter to assets that overlap the given time window (start/end in seconds).
        Always call this before update_asset or delete_asset to get the asset ID.
        If the timeline has many assets (e.g. dense captions), an unfiltered call will be
        refused — pass a start/end window and query a few minutes at a time instead."""
        from videos.models import VideoJob
        j = VideoJob.objects.get(pk=job_pk)
        assets = j.assets or []
        windowed = start is not None and end is not None
        if windowed:
            assets = [a for a in assets if a['start'] < end and a['end'] > start]
        if not assets:
            return "No assets on the timeline" + (f" between {_fmt_time(start)} and {_fmt_time(end)}" if start is not None else "") + "."
        # Unfiltered + too many to list safely — refuse and push the agent toward a
        # windowed query instead of returning a response that could exceed the context limit.
        if not windowed and len(assets) > _MAX_ASSETS_UNFILTERED:
            timeline_end = max(a['end'] for a in assets)
            return (
                f"{len(assets)} assets on the timeline — too many to list at once. "
                f"Timeline spans 0:00–{_fmt_time(timeline_end)}. "
                f"Call read_assets again with a start/end window (e.g. a few minutes at a time) "
                f"to see individual assets."
            )
        lines = [f"{len(assets)} asset(s):"]
        for a in assets:
            style = a.get('style', {})
            content = a.get('content', {})
            base = (
                f"  id={a['id']} [{_fmt_time(a['start'])}–{_fmt_time(a['end'])}] "
                f"type={a['type']} layer={a.get('layer', '?')} "
                f"pos=({a['position']['x']:.2f},{a['position']['y']:.2f}) "
            )
            if a['type'] == 'image':
                lines.append(
                    base
                    + f"width_pct={style.get('width_pct', '?')} "
                    f"corner_radius_pct={style.get('corner_radius_pct', 0)} "
                    f"opacity={style.get('opacity', 1.0)} "
                    f"border_color={style.get('border_color', 'none')} "
                    f"border_width_pct={style.get('border_width_pct', 0)} "
                    f"name=\"{content.get('name', '?')}\""
                )
            else:
                lines.append(
                    base
                    + f"font_size={style.get('font_size', '?')} "
                    f"color={style.get('color', '?')} "
                    f"bg={style.get('background', '?')} "
                    f"highlight_color={style.get('highlight_color', 'none')} "
                    f"\"{content.get('text', '')[:50]}\""
                )
        return "\n".join(lines)

    @tool
    def list_uploaded_files() -> str:
        """List images (and PDF pages, already rasterized to images) the user has uploaded
        from the Assets panel. Use this to find the exact file id when the user refers to an
        uploaded file by description (e.g. "the logo", "my PDF") before calling insert_image_asset."""
        from videos.models import VideoJob, UploadedAsset
        j = VideoJob.objects.get(pk=job_pk)
        files = j.uploaded_assets.filter(kind=UploadedAsset.Kind.IMAGE)
        if not files:
            return "No uploaded files yet — the user needs to upload an image or PDF from the Assets panel first."
        placed_ids = {a.get('content', {}).get('file_id') for a in (j.assets or [])}
        lines = ["Uploaded image(s):"]
        for f in files:
            source = f" (page {f.page_number} of \"{f.source_pdf.original_name}\")" if f.source_pdf_id else ""
            status = "already placed on timeline" if f.pk in placed_ids else "not yet placed"
            lines.append(f"  id={f.pk} name=\"{f.original_name}\"{source} — {status}")
        return "\n".join(lines)

    @tool
    def insert_image_asset(
        file_id: int,
        start: float,
        end: float,
        halign: str = "center",
        valign: str = "middle",
        width_pct: float = 0.3,
        corner_radius_pct: float = 0.0,
        opacity: float = 1.0,
        border_color: str = None,
        border_width_pct: float = 0.0,
    ) -> str:
        """Place a previously uploaded image (or rasterized PDF page) onto the video timeline
        between start and end (seconds). file_id comes from list_uploaded_files — call that
        first if you don't already know the id.
        halign: 'left', 'center', or 'right' (default 'center').
        valign: 'top', 'middle', or 'bottom' (default 'middle').
        width_pct: image width as a fraction of the video's width, 0-1 (default 0.3).
        Height scales automatically to preserve the image's aspect ratio.
        corner_radius_pct: rounds the image's corners, 0-0.5 as a fraction of its
        shorter side (0 = square corners, 0.5 = fully round/pill-shaped). Default 0.
        opacity: 0-1, image transparency (default 1.0 = fully opaque).
        border_color: hex string e.g. '#FFFFFF' to draw a border around the image (default none).
        border_width_pct: border thickness, 0-0.5 as a fraction of the image's shorter side.
        Only applies if border_color is also set.
        Changes appear instantly in the browser preview — no render needed."""
        from django.db import transaction
        from videos.models import VideoJob, UploadedAsset

        try:
            file = UploadedAsset.objects.get(pk=file_id, job_id=job_pk, kind=UploadedAsset.Kind.IMAGE)
        except UploadedAsset.DoesNotExist:
            return f"No uploaded image found with id {file_id}. Use list_uploaded_files to see available files."

        x = _HALIGN_X.get(halign, 0.5)
        y = _VALIGN_Y.get(valign, 0.5)

        new_asset = {
            'id': str(uuid.uuid4()),
            'type': 'image',
            'source': 'upload',
            'start': start,
            'end': end,
            'layer': 1,
            'position': {'x': x, 'y': y, 'anchor': 'center'},
            # 'path' is a local filesystem path used only by the (Django-free)
            # render pipeline — 'url' is what the browser preview loads.
            'content': {'file_id': file.pk, 'url': file.file.url, 'path': file.file.path, 'name': file.original_name},
            'style': {
                'width_pct': width_pct,
                'corner_radius_pct': corner_radius_pct,
                'opacity': opacity,
                'border_color': border_color,
                'border_width_pct': border_width_pct,
            },
        }

        with transaction.atomic():
            j = VideoJob.objects.select_for_update().get(pk=job_pk)
            assets = j.assets or []
            overlapping = [a for a in assets if a.get('type') == 'image' and a['start'] < end and a['end'] > start]
            assets.append(new_asset)
            j.assets = assets
            update_fields = ["assets"]
            if j.stage == VideoJob.Stage.RENDERED:
                j.stage = VideoJob.Stage.CAPTIONED
                update_fields.append("stage")
            j.save(update_fields=update_fields)

        overlap_note = f" Note: overlaps {len(overlapping)} other image asset(s) in the same time range." if overlapping else ""
        return f"Image \"{file.original_name}\" placed at {_fmt_time(start)}–{_fmt_time(end)}.{overlap_note}"

    @tool
    def update_image_asset(
        id: str,
        start: float = None,
        end: float = None,
        halign: str = None,
        valign: str = None,
        width_pct: float = None,
        corner_radius_pct: float = None,
        opacity: float = None,
        border_color: str = None,
        border_width_pct: float = None,
    ) -> str:
        """Update an image asset already on the timeline by its ID. Only the fields you pass
        will be changed. Use read_assets first to get the asset ID — only works on type='image' assets.
        halign: 'left', 'center', 'right'. valign: 'top', 'middle', 'bottom'.
        width_pct: image width as a fraction of the video's width, 0-1.
        corner_radius_pct: 0-0.5 as a fraction of the image's shorter side (0 = square corners).
        opacity: 0-1.
        border_color: hex string e.g. '#FFFFFF', or 'none' to remove an existing border.
        border_width_pct: 0-0.5 as a fraction of the image's shorter side.
        Changes appear instantly in the browser preview — no render needed."""
        from django.db import transaction
        from videos.models import VideoJob

        with transaction.atomic():
            j = VideoJob.objects.select_for_update().get(pk=job_pk)
            assets = j.assets or []

            asset = next((a for a in assets if a['id'] == id), None)
            if not asset:
                return f"No asset found with id {id}. Use read_assets to list available IDs."
            if asset.get('type') != 'image':
                return f"Asset {id[:8]}… is type='{asset.get('type')}', not an image. Use update_asset for text/caption assets instead."

            if start is not None:
                asset['start'] = start
            if end is not None:
                asset['end'] = end
            if halign is not None:
                asset['position']['x'] = _HALIGN_X.get(halign, asset['position']['x'])
            if valign is not None:
                asset['position']['y'] = _VALIGN_Y.get(valign, asset['position']['y'])

            style = asset.setdefault('style', {})
            if width_pct is not None:
                style['width_pct'] = width_pct
            if corner_radius_pct is not None:
                style['corner_radius_pct'] = corner_radius_pct
            if opacity is not None:
                style['opacity'] = opacity
            if border_color is not None:
                style['border_color'] = None if border_color.lower() == 'none' else border_color
            if border_width_pct is not None:
                style['border_width_pct'] = border_width_pct

            j.assets = assets
            update_fields = ["assets"]
            if j.stage == VideoJob.Stage.RENDERED:
                j.stage = VideoJob.Stage.CAPTIONED
                update_fields.append("stage")
            j.save(update_fields=update_fields)

        return f"Image asset {id[:8]}… updated. The live preview will reflect the change — no re-render needed."

    @tool
    def insert_asset(
        text: str,
        start: float,
        end: float,
        halign: str = "center",
        valign: str = "top",
        font_size: int = 72,
        color: str = "#FFFFFF",
        background: str = "dark",
    ) -> str:
        """Insert a text overlay into the asset timeline at the given time range.
        start and end are in seconds (e.g. 3:02 = 182.0).
        halign: 'left', 'center', or 'right' (default 'center').
        valign: 'top', 'middle', or 'bottom' (default 'top' to avoid overlapping caption strip at bottom).
        font_size: in points, default 72.
        color: hex string e.g. '#FF0000' (default white '#FFFFFF').
        background: 'none', 'dark' (semi-transparent black box), or 'light' (semi-transparent white box). Default 'dark'.
        Changes appear instantly in the browser preview — no render needed."""
        from django.db import transaction
        from videos.models import VideoJob

        x = _HALIGN_X.get(halign, 0.5)
        y = _VALIGN_Y.get(valign, 0.1)

        new_asset = {
            'id': str(uuid.uuid4()),
            'type': 'text',
            'source': 'manual',
            'start': start,
            'end': end,
            'layer': 2,
            'position': {'x': x, 'y': y, 'anchor': 'center'},
            'content': {'text': text},
            'style': {
                'font': 'Roboto',
                'font_size': font_size,
                'font_weight': 'Regular',
                'font_italic': False,
                'color': color,
                'background': background,
            },
        }

        with transaction.atomic():
            j = VideoJob.objects.select_for_update().get(pk=job_pk)
            assets = j.assets or []
            overlapping = [a for a in assets if a['start'] < end and a['end'] > start]
            assets.append(new_asset)
            j.assets = assets
            # If a previous render exists, mark it stale so the UI shows "Render & Download"
            # instead of pointing at the old output file.
            update_fields = ["assets"]
            if j.stage == VideoJob.Stage.RENDERED:
                j.stage = VideoJob.Stage.CAPTIONED
                update_fields.append("stage")
            j.save(update_fields=update_fields)

        overlap_note = ""
        if overlapping:
            descriptions = [
                f"[{_fmt_time(a['start'])}–{_fmt_time(a['end'])}] \"{a['content']['text'][:30]}\""
                for a in overlapping[:3]
            ]
            overlap_note = f" Note: overlaps {len(overlapping)} existing asset(s): {'; '.join(descriptions)}."

        return f"Text overlay \"{text}\" inserted at {_fmt_time(start)}–{_fmt_time(end)}.{overlap_note}"

    @tool
    def update_asset(
        id: str,
        text: str = None,
        start: float = None,
        end: float = None,
        halign: str = None,
        valign: str = None,
        font_size: int = None,
        color: str = None,
        background: str = None,
        font: str = None,
        font_weight: str = None,
        font_italic: bool = None,
        highlight_color: str = None,
    ) -> str:
        """Update a single asset on the timeline by its ID. Only the fields you pass will be changed.
        Use read_assets first to get the asset ID.
        For applying the same change to ALL captions at once, use bulk_update_captions instead — never loop this tool.
        halign: 'left', 'center', 'right'. valign: 'top', 'middle', 'bottom'.
        color: hex string e.g. '#FF0000'. background: 'none', 'dark', or 'light'.
        font: one of 'Roboto', 'Montserrat', 'Oswald', 'Gelasio', 'Anton', 'Bebas Neue',
        'Archivo Black', 'Bangers', 'Alfa Slab One', 'Luckiest Guy', 'Caveat', 'Pacifico',
        'Dancing Script', 'Permanent Marker', 'Kalam', 'Playfair Display', 'Merriweather',
        'Lora', 'Libre Baskerville', 'JetBrains Mono', 'Space Mono', 'IBM Plex Mono',
        'Roboto Mono', 'Inter', 'Poppins' — no other font names are available.
        font_weight: 'Regular', 'Bold', 'SemiBold', 'Light', etc.
        font_italic: true or false.
        highlight_color: hex string, e.g. '#F59E0B', for reels/TikTok-style word-by-word
        highlighting — only applies to caption assets (they carry per-word timestamps);
        the currently-spoken word gets a highlighted background pill that moves as it plays.
        Pass 'none' to turn highlighting back off. There is no default — ask the user what
        color they want, since this is purely a stylistic choice.
        Changes appear instantly in the browser preview — no render needed."""
        from django.db import transaction
        from videos.models import VideoJob

        if font is not None:
            _validate_font(font)

        with transaction.atomic():
            j = VideoJob.objects.select_for_update().get(pk=job_pk)
            assets = j.assets or []

            asset = next((a for a in assets if a['id'] == id), None)
            if not asset:
                return f"No asset found with id {id}. Use read_assets to list available IDs."

            if text is not None:
                asset['content']['text'] = text
            if start is not None:
                asset['start'] = start
            if end is not None:
                asset['end'] = end
            if halign is not None:
                asset['position']['x'] = _HALIGN_X.get(halign, asset['position']['x'])
            if valign is not None:
                asset['position']['y'] = _VALIGN_Y.get(valign, asset['position']['y'])

            style = asset.setdefault('style', {})
            if font_size is not None:
                style['font_size'] = font_size
            if color is not None:
                style['color'] = color
            if background is not None:
                style['background'] = background
            if font is not None:
                style['font'] = font
            if font_weight is not None:
                style['font_weight'] = font_weight
            if font_italic is not None:
                style['font_italic'] = font_italic
            if highlight_color is not None:
                style['highlight_color'] = None if highlight_color.lower() == 'none' else highlight_color

            j.assets = assets
            # If a previous render exists, mark it stale so the UI shows "Render & Download".
            update_fields = ["assets"]
            if j.stage == VideoJob.Stage.RENDERED:
                j.stage = VideoJob.Stage.CAPTIONED
                update_fields.append("stage")
            j.save(update_fields=update_fields)

        return f"Asset {id[:8]}… updated. The live preview will reflect the change — no re-render needed."

    @tool
    def bulk_update_captions(
        text_transform: str = None,
        font_weight: str = None,
        font_size: int = None,
        color: str = None,
        background: str = None,
        font: str = None,
        font_italic: bool = None,
        highlight_color: str = None,
    ) -> str:
        """Apply a style change or text transform to ALL caption assets in one operation.
        Use this instead of calling update_asset in a loop — it is reliable, atomic, and uses a single database write.
        Never loop update_asset for global caption changes; always use this tool instead.
        text_transform: 'uppercase', 'lowercase', or 'titlecase' — transforms every caption's text.
        All style params (font_weight, font_size, color, background, font, font_italic) work the same as update_asset.
        font: one of 'Roboto', 'Montserrat', 'Oswald', 'Gelasio', 'Anton', 'Bebas Neue',
        'Archivo Black', 'Bangers', 'Alfa Slab One', 'Luckiest Guy', 'Caveat', 'Pacifico',
        'Dancing Script', 'Permanent Marker', 'Kalam', 'Playfair Display', 'Merriweather',
        'Lora', 'Libre Baskerville', 'JetBrains Mono', 'Space Mono', 'IBM Plex Mono',
        'Roboto Mono', 'Inter', 'Poppins' — no other font names are available.
        highlight_color: hex string, e.g. '#F59E0B', for reels/TikTok-style word-by-word
        highlighting — the currently-spoken word gets a highlighted background pill that
        moves as it plays. Pass 'none' to turn highlighting back off. There is no default —
        ask the user what color they want, since this is purely a stylistic choice.
        Changes appear instantly in the browser preview — no render needed."""
        from django.db import transaction
        from videos.models import VideoJob

        if font is not None:
            _validate_font(font)

        # Map text_transform string to the corresponding str method
        transform_fn = {
            'uppercase': str.upper,
            'lowercase': str.lower,
            'titlecase': str.title,
        }.get(text_transform.lower() if text_transform else '', None)

        with transaction.atomic():
            j = VideoJob.objects.select_for_update().get(pk=job_pk)
            assets = j.assets or []

            # Only touch caption-type assets; leave manual text overlays alone
            updated = 0
            for asset in assets:
                if asset.get('type') != 'caption':
                    continue

                if transform_fn is not None:
                    asset['content']['text'] = transform_fn(asset['content']['text'])

                style = asset.setdefault('style', {})
                if font_size is not None:
                    style['font_size'] = font_size
                if color is not None:
                    style['color'] = color
                if background is not None:
                    style['background'] = background
                if font is not None:
                    style['font'] = font
                if font_weight is not None:
                    style['font_weight'] = font_weight
                if font_italic is not None:
                    style['font_italic'] = font_italic
                if highlight_color is not None:
                    style['highlight_color'] = None if highlight_color.lower() == 'none' else highlight_color

                updated += 1

            if updated == 0:
                return "No caption assets found on the timeline."

            j.assets = assets
            # Mark render stale so the UI shows "Render & Download" rather than the old file
            update_fields = ["assets"]
            if j.stage == VideoJob.Stage.RENDERED:
                j.stage = VideoJob.Stage.CAPTIONED
                update_fields.append("stage")
            j.save(update_fields=update_fields)

        parts = []
        if transform_fn is not None:
            parts.append(f"text → {text_transform}")
        if font_weight is not None:
            parts.append(f"font_weight={font_weight}")
        if font_size is not None:
            parts.append(f"font_size={font_size}")
        if color is not None:
            parts.append(f"color={color}")
        if background is not None:
            parts.append(f"background={background}")
        if font is not None:
            parts.append(f"font={font}")
        if font_italic is not None:
            parts.append(f"font_italic={font_italic}")
        if highlight_color is not None:
            parts.append(f"highlight_color={highlight_color}")
        change_summary = ", ".join(parts) if parts else "no changes specified"
        return f"Updated {updated} caption(s): {change_summary}. Preview reflects the change — no re-render needed."

    @tool
    def delete_asset(id: str) -> str:
        """Remove an asset from the timeline by its ID.
        Use read_assets first to get the asset ID.
        The change is instant — no re-render needed for preview."""
        from django.db import transaction
        from videos.models import VideoJob

        with transaction.atomic():
            j = VideoJob.objects.select_for_update().get(pk=job_pk)
            assets = j.assets or []

            before = len(assets)
            assets = [a for a in assets if a['id'] != id]
            if len(assets) == before:
                return f"No asset found with id {id}. Use read_assets to list available IDs."

            j.assets = assets
            # If a previous render exists, mark it stale so the UI shows "Render & Download".
            update_fields = ["assets"]
            if j.stage == VideoJob.Stage.RENDERED:
                j.stage = VideoJob.Stage.CAPTIONED
                update_fields.append("stage")
            j.save(update_fields=update_fields)

        return f"Asset {id[:8]}… deleted. {len(assets)} asset(s) remain on the timeline."

    @tool
    def check_transcript_quality() -> str:
        """Check the quality of the existing transcript using Whisper confidence scores.
        Call this when the user doubts the transcript accuracy."""
        from videos.models import VideoJob
        j = VideoJob.objects.get(pk=job_pk)
        if not j.transcript:
            return "No transcript yet. Run transcribe_video first."

        segments = j.transcript.get('segments', [])
        words = j.transcript.get('words', [])

        low_conf_segments = [s for s in segments if s.get('avg_logprob', 0) < -1.0]
        noise_segments = [s for s in segments if s.get('no_speech_prob', 0) > 0.5]
        low_conf_words = [w for w in words if w.get('probability', 1.0) < 0.7]

        lines = ["Transcript quality report:"]

        if not low_conf_segments and not noise_segments and not low_conf_words:
            lines.append("All segments and words look good — no low-confidence areas detected.")
            return "\n".join(lines)

        if low_conf_segments:
            lines.append(f"\n{len(low_conf_segments)} low-confidence segment(s) (avg_logprob < -1.0):")
            for s in low_conf_segments[:5]:
                lines.append(
                    f"  [{_fmt_time(s.get('start'))}–{_fmt_time(s.get('end'))}]"
                    f" \"{s.get('text', '').strip()}\""
                    f" (logprob: {s.get('avg_logprob', 0):.2f})"
                )
            if len(low_conf_segments) > 5:
                lines.append(f"  ... and {len(low_conf_segments) - 5} more")

        if noise_segments:
            lines.append(f"\n{len(noise_segments)} possible silence/noise segment(s) (no_speech_prob > 0.5):")
            for s in noise_segments[:3]:
                lines.append(
                    f"  [{_fmt_time(s.get('start'))}–{_fmt_time(s.get('end'))}]"
                    f" \"{s.get('text', '').strip()}\""
                    f" (no_speech_prob: {s.get('no_speech_prob', 0):.2f})"
                )
            if len(noise_segments) > 3:
                lines.append(f"  ... and {len(noise_segments) - 3} more")

        if low_conf_words:
            lines.append(f"\n{len(low_conf_words)} low-confidence word(s) (probability < 0.7):")
            word_list = [
                f"\"{w.get('word', '').strip()}\" at {_fmt_time(w.get('start'))} ({w.get('probability', 0):.0%})"
                for w in low_conf_words[:8]
            ]
            lines.append("  " + ", ".join(word_list))
            if len(low_conf_words) > 8:
                lines.append(f"  ... and {len(low_conf_words) - 8} more")

        return "\n".join(lines)

    @tool
    def read_ui_map(question: str = None) -> str:
        """Look up where a button, tab, or panel is in the app's UI.
        Call this whenever the user asks "where is X", "how do I find X", or seems
        confused about the app's layout — never guess at UI locations from memory.
        question is optional free text describing what the user is looking for (not
        used to filter, just for your own framing); the full UI map is always returned."""
        if not _UI_MAP_PATH.exists():
            return "UI_MAP.md not found — cannot answer layout questions right now."
        return _UI_MAP_PATH.read_text(encoding="utf-8")  # small doc, fine to return whole file

    tools = [
        generate_captions, read_assets,
        insert_asset, update_asset, bulk_update_captions, delete_asset,
        list_uploaded_files, insert_image_asset, update_image_asset,
        check_transcript_quality, read_transcript, read_ui_map,
    ]
    # Omit transcribe_video entirely when the Groq backend isn't configured, rather than
    # letting the agent call it and fail — this way a missing/expired key costs one LLM
    # turn (composing the "unavailable" reply from the system prompt note below) instead
    # of a wasted tool round-trip plus ffmpeg extraction that was always going to fail.
    if transcription_available():
        tools.insert(0, transcribe_video)
    return tools


# Subset of make_tools()'s tools also shown to the user as a clickable "Skill" card
# in the Skills tab (job_detail.html) — clicking one inserts `prompt` into the chat
# input for the user to send/edit. Everything else make_tools() returns is agent-only:
# it either needs an asset id the user has no way of knowing (update_asset,
# update_image_asset, delete_asset), or is a read-only lookup the agent calls for
# itself mid-conversation (read_assets, read_transcript, list_uploaded_files,
# read_ui_map). Defined here (not duplicated in the template/JS) so this list can't
# drift from the actual tool names the way _AVAILABLE_FONTS/_FONT_FAMILIES can.
# Cards are shown unconditionally regardless of job stage — if a skill isn't valid
# yet (e.g. Generate Captions before transcribing), the tool's own existing guard
# message handles it (see generate_captions above).
USER_FACING_SKILLS = [
    {"tool": "transcribe_video", "label": "Transcribe",
     "description": "Extract the spoken words and timestamps.",
     "prompt": "Transcribe this video"},
    {"tool": "generate_captions", "label": "Generate Captions",
     "description": "Turn the transcript into timed caption chunks.",
     "prompt": "Generate captions"},
    {"tool": "insert_asset", "label": "Add Text Overlay",
     "description": "Place a custom text overlay on the timeline.",
     "prompt": "Add a text overlay that says \"...\" from 0:00 to 0:05"},
    {"tool": "insert_image_asset", "label": "Place an Image",
     "description": "Put an uploaded image or PDF page onto the timeline.",
     "prompt": "Place [uploaded file name] on the timeline from 0:00 to 0:05"},
    {"tool": "check_transcript_quality", "label": "Check Transcript Quality",
     "description": "Flag low-confidence words or silence in the transcript.",
     "prompt": "Check the transcript quality"},
    {"tool": "bulk_update_captions", "label": "Restyle Captions",
     "description": "Change the look of every caption at once.",
     "prompt": "Change the caption style: make the font bold and the color amber"},
]
