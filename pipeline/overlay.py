import subprocess
import os
import tempfile

# FONTS_DIR moved to layers/base.py so layer modules can resolve fonts without
# importing this module back (overlay.py imports the layer modules — a
# same-direction import here would be a cycle). Aliased to keep local naming.
from pipeline.layers.base import FONTS_DIR as _FONTS_DIR
from pipeline.layers.base import LayerContext
# Caption layer module: renders word-highlighted captions with Pillow so the
# highlight pill and the text are laid out by one engine (see docs/plan.md);
# plain captions still go through the ASS path below.
from pipeline.layers import caption as caption_layer

_PLAY_RES_X = 1920
_PLAY_RES_Y = 1080

# Maps resolution label → output height; width is auto-calculated by ffmpeg to
# preserve aspect ratio (-2 rounds to nearest even, required by libx264).
_RESOLUTION_HEIGHTS = {
    '1080p': 1080,
    '720p':  720,
    '480p':  480,
}

_ASS_HEADER = f"""\
[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {_PLAY_RES_X}
PlayResY: {_PLAY_RES_Y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Roboto,72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H55000000,1,0,0,0,100,100,0,0,1,4,3,5,10,10,0,1
Style: DarkBG,Roboto,72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,3,8,0,5,10,10,0,1
Style: LightBG,Roboto,72,&H00000000,&H00000000,&H00FFFFFF,&H80FFFFFF,1,0,0,0,100,100,0,0,3,8,0,5,10,10,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# Weight names treated as bold when building ASS inline tags — kept in sync
# with BOLD_WEIGHTS in layers/base.py (same set, used there for font-file picks).
_BOLD_WEIGHTS = {"semibold", "bold", "extrabold", "black"}


def _seconds_to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int((s % 1) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def _hex_to_ass_color(hex_color: str) -> str:
    h = hex_color.lstrip('#')
    r, g, b = h[0:2], h[2:4], h[4:6]
    # Only the hex digits are case-insensitive in ASS — the \c tag name itself is
    # case-sensitive (libass silently ignores \C and falls back to the style's
    # default color), so .upper() must not touch the leading "\\c".
    return "\\c&H" + f"{b}{g}{r}".upper() + "&"


def _pick_style(background: str) -> str:
    if not background or background == "none":
        return "Default"
    if background == "light":
        return "LightBG"
    return "DarkBG"


def _build_inline_tags(style: dict) -> str:
    parts = []
    # \fn sets the font family; must come before bold/italic/size so they apply to the new face
    font = style.get('font')
    if font:
        parts.append(f"\\fn{font}")
    weight = style.get('font_weight', 'Regular')
    if weight.strip().lower() in _BOLD_WEIGHTS:
        parts.append("\\b1")
    if style.get('font_italic', False):
        parts.append("\\i1")
    parts.append(f"\\fs{int(style.get('font_size', 72))}")
    try:
        parts.append(_hex_to_ass_color(style.get('color', '#FFFFFF')))
    except Exception:
        parts.append("\\c&H00FFFFFF&")
    return "{" + "".join(parts) + "}"


def _write_ass_file(assets: list[dict]) -> str:
    lines = [_ASS_HEADER.rstrip()]

    for asset in sorted(assets, key=lambda a: a.get('layer', 1)):
        if asset.get('type') not in ('caption', 'text'):
            continue
        # Word-highlighted captions are rendered by the Pillow caption layer
        # (pipeline/layers/caption.py) as timed overlay inputs instead — the old
        # ASS vector-box approach positioned the pill with a second layout engine
        # and drifted from the text (docs/plan.md). Skipping here (same is_dynamic
        # check composite_overlay routes with) guarantees exactly one renderer
        # ever draws a given caption.
        if caption_layer.is_dynamic(asset):
            continue

        start = _seconds_to_ass_time(asset['start'])
        end = _seconds_to_ass_time(asset['end'])

        pos = asset.get('position', {'x': 0.5, 'y': 0.85})
        x_px = int(pos.get('x', 0.5) * _PLAY_RES_X)
        y_px = int(pos.get('y', 0.85) * _PLAY_RES_Y)

        style = asset.get('style', {})
        style_name = _pick_style(style.get('background'))
        fmt_tags = _build_inline_tags(style)

        text = asset['content']['text'].replace('\n', '\\N')
        pos_tag = "{\\an5\\pos(" + str(x_px) + "," + str(y_px) + ")}"

        lines.append(f"Dialogue: 0,{start},{end},{style_name},,0,0,0,,{pos_tag}{fmt_tags}{text}")

    fd, path = tempfile.mkstemp(suffix=".ass")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def _style_image(path: str, style: dict) -> str | None:
    """Bakes rounded corners / opacity / border into a temp RGBA PNG if the asset's
    style requests any of them; returns None (use the original file as-is) when no
    styling is set, so the common unstyled case skips a lossy PNG re-encode."""
    radius_pct = style.get('corner_radius_pct') or 0
    opacity = style.get('opacity')
    opacity = 1.0 if opacity is None else opacity
    border_width_pct = style.get('border_width_pct') or 0
    border_color = style.get('border_color')
    has_border = border_width_pct > 0 and border_color

    if radius_pct <= 0 and opacity >= 1.0 and not has_border:
        return None

    from PIL import Image, ImageDraw

    img = Image.open(path).convert("RGBA")
    w, h = img.size
    short_side = min(w, h)
    # Radius/border are stored as a % of the image's own shorter side rather than
    # absolute pixels, so they scale correctly no matter what width_pct/output
    # resolution the ffmpeg `scale` filter later resizes this image to.
    radius = int(radius_pct * short_side)
    border_width = int(border_width_pct * short_side) if has_border else 0

    if radius > 0:
        # Rounded-corner alpha mask, intersected with the image's existing alpha
        # so a transparent source PNG (e.g. a logo) doesn't get corners "filled in".
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
        r, g, b, a = img.split()
        a = Image.composite(a, Image.new("L", (w, h), 0), mask)
        img = Image.merge("RGBA", (r, g, b, a))

    if opacity < 1.0:
        r, g, b, a = img.split()
        a = a.point(lambda px: int(px * opacity))
        img = Image.merge("RGBA", (r, g, b, a))

    if has_border:
        # Inset by half the stroke width so the outline is drawn centered on the
        # image edge rather than clipped outside it.
        inset = border_width / 2
        ImageDraw.Draw(img).rounded_rectangle(
            [inset, inset, w - 1 - inset, h - 1 - inset],
            radius=max(0, radius - border_width // 2),
            outline=border_color,
            width=border_width,
        )

    fd, out_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img.save(out_path, "PNG")
    return out_path


def _build_filter_complex(
    image_assets: list[dict],
    caption_overlays: list[dict],
    out_w: int,
    out_h: int,
    sub_filter: str,
    scale_filter: str | None,
) -> str:
    # Builds a filter_complex graph: base video -> one overlay step per image
    # (in layer order) -> one overlay step per pre-rendered caption-layer PNG
    # (so highlighted captions paint on top of images, like ASS captions do)
    # -> ASS subtitles burned in last, so plain captions/text always stay
    # readable on top of everything. Input indexing must match the -i order
    # composite_overlay builds: video, then image files, then caption PNGs.
    parts = []
    base_label = "0:v"
    if scale_filter:
        parts.append(f"[0:v]{scale_filter}[scaled]")
        base_label = "scaled"

    current = f"[{base_label}]"
    for i, asset in enumerate(image_assets):
        style = asset.get('style', {})
        pos = asset.get('position', {'x': 0.5, 'y': 0.5})
        width_px = max(1, round(style.get('width_pct', 0.3) * out_w))
        img_input = i + 1  # ffmpeg input index; 0 is the main video
        scaled_label = f"img{i}"
        # -1 preserves the image's own aspect ratio; only the base video frame
        # needs an even dimension for the encoder.
        parts.append(f"[{img_input}:v]scale={width_px}:-1[{scaled_label}]")

        # asset.position is the image's CENTER (0-1 normalized); overlay expects
        # the top-left pixel, so shift back by half the (now-known) overlay size.
        x_expr = f"({pos.get('x', 0.5)}*{out_w})-(overlay_w/2)"
        y_expr = f"({pos.get('y', 0.5)}*{out_h})-(overlay_h/2)"
        enable = f"between(t,{asset['start']},{asset['end']})"
        out_label = f"ov{i}"
        parts.append(f"{current}[{scaled_label}]overlay=x='{x_expr}':y='{y_expr}':enable='{enable}'[{out_label}]")
        current = f"[{out_label}]"

    for j, item in enumerate(caption_overlays):
        # Caption-layer PNGs are already rendered at output resolution with
        # their top-left placement precomputed (render_overlays), so no scale
        # step and no center-shift expressions — just a timed overlay.
        cap_input = 1 + len(image_assets) + j
        out_label = f"cap{j}"
        parts.append(
            f"{current}[{cap_input}:v]overlay=x={item['x']}:y={item['y']}:enable='{item['enable']}'[{out_label}]"
        )
        current = f"[{out_label}]"

    parts.append(f"{current}{sub_filter}[outv]")
    return ";".join(parts)


def _run_ffmpeg_with_progress(cmd, total_duration, progress_callback):
    # Runs an ffmpeg command while streaming its encode position back through
    # progress_callback(percent) — this is what lets the Export button show a
    # real progress bar instead of an indeterminate spinner.
    # -progress pipe:1 makes ffmpeg emit machine-readable key=value progress
    # lines on stdout; -nostats silences the human-readable stderr ticker so
    # stderr only holds real diagnostics (read back on failure below).
    full_cmd = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
    # A zero/negative duration would divide by zero below; run without progress
    # reporting rather than fail the whole render over a broken container header.
    if total_duration <= 0:
        progress_callback = None
    # stderr goes to a temp file, not a pipe — we only read stdout during the
    # encode, and an unread stderr PIPE could fill its OS buffer and deadlock
    # ffmpeg on a chatty run (e.g. per-event subtitle warnings).
    with tempfile.TemporaryFile() as err_file:
        proc = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=err_file)
        last_pct = -1  # last percent reported, so the callback (a DB write) only fires on change
        # The loop must always drain stdout even when nobody wants progress —
        # an unread stdout PIPE would fill up and stall ffmpeg mid-encode.
        for raw_line in proc.stdout:
            if not progress_callback:
                continue
            line = raw_line.decode("utf-8", errors="replace").strip()
            # out_time_us is the encoded position in microseconds — the only
            # progress key we need; everything else (fps, bitrate…) is ignored.
            if not line.startswith("out_time_us="):
                continue
            value = line.split("=", 1)[1]
            # ffmpeg emits "N/A" before the first frame is written — skip those.
            if not value.lstrip("-").isdigit():
                continue
            # Clamp to 0–99: 100 is reserved for "actually finished" so the UI
            # never shows a full bar while ffmpeg is still muxing/finalizing.
            pct = max(0, min(99, int(int(value) / 1_000_000 / total_duration * 100)))
            if pct > last_pct:
                progress_callback(pct)
                last_pct = pct
        proc.wait()
        if proc.returncode != 0:
            # Surface ffmpeg's own diagnostics as the job error message, same
            # contract the old subprocess.run(capture_output=True) path had.
            err_file.seek(0)
            raise RuntimeError(err_file.read().decode("utf-8", errors="replace"))


def composite_overlay(
    video_path: str,
    assets: list[dict],
    output_path: str,
    resolution: str = 'original',
    progress_callback=None,
) -> str:
    # Real output dimensions are needed unconditionally: the caption layer
    # renders its PNGs at output resolution, and image overlay sizes are
    # computed against the real (even-rounded) output width.
    from pipeline.captions import _get_aspect_ratio
    src_w, src_h = _get_aspect_ratio(video_path)
    height = _RESOLUTION_HEIGHTS.get(resolution)
    if height:
        out_h = height
        # Same even-width rounding ffmpeg's scale=-2:H applies, computed here in
        # Python so overlay sizes/positions use the real output width.
        out_w = round(src_w * out_h / src_h / 2) * 2
    else:
        out_w, out_h = src_w, src_h

    sorted_assets = sorted(assets, key=lambda a: a.get('layer', 1))
    image_assets = [a for a in sorted_assets if a.get('type') == 'image']
    # Dynamic caption layers: word-highlighted captions the Pillow caption layer
    # renders (pipeline/layers/caption.py); _write_ass_file skips these via the
    # same is_dynamic check, so each caption has exactly one renderer.
    dynamic_captions = [a for a in sorted_assets if caption_layer.is_dynamic(a)]

    ctx = LayerContext(out_w=out_w, out_h=out_h)
    caption_overlays = []  # {'path','x','y','enable'} per pre-rendered caption state
    temp_paths = []        # every temp file we create, cleaned up in finally
    try:
        for asset in dynamic_captions:
            items = caption_layer.render_overlays(asset, ctx)
            caption_overlays += items
            temp_paths += [item['path'] for item in items]

        ass_path = _write_ass_file(assets)
        temp_paths.append(ass_path)

        ass_ffmpeg = ass_path.replace("\\", "/").replace(":", "\\:")
        fonts_ffmpeg = _FONTS_DIR.replace("\\", "/").replace(":", "\\:")

        sub_filter = f"subtitles='{ass_ffmpeg}':fontsdir='{fonts_ffmpeg}'"
        # scale=-2:H preserves aspect ratio and ensures width is even (libx264 requirement).
        scale_filter = f"scale=-2:{height}" if height else None

        if not image_assets and not caption_overlays:
            # Nothing on the timeline needs extra inputs — keep the original
            # single -vf path (simpler command, unchanged from before overlays existed).
            vf = f"{scale_filter},{sub_filter}" if scale_filter else sub_filter
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vf", vf,
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "copy",
                output_path,
            ]
        else:
            filter_complex = _build_filter_complex(
                image_assets, caption_overlays, out_w, out_h, sub_filter, scale_filter
            )

            # Input order must match _build_filter_complex's indexing:
            # video (0), image files (1..N), caption-state PNGs (N+1..).
            cmd = ["ffmpeg", "-y", "-i", video_path]
            for asset in image_assets:
                styled_path = _style_image(asset['content']['path'], asset.get('style', {}))
                if styled_path:
                    temp_paths.append(styled_path)
                cmd += ["-i", styled_path or asset['content']['path']]
            for item in caption_overlays:
                cmd += ["-i", item['path']]
            cmd += [
                "-filter_complex", filter_complex,
                "-map", "[outv]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "copy",
                output_path,
            ]

        # Source duration ≈ output duration (we never trim), so encode position
        # over source duration gives the percent for the Export progress bar.
        # Local import to mirror the _get_aspect_ratio pattern above and avoid
        # pulling transcribe.py's Groq client into every overlay import.
        total_duration = 0.0
        if progress_callback:
            from pipeline.transcribe import get_duration_seconds
            try:
                total_duration = get_duration_seconds(video_path)
            except Exception:
                # A failed probe only costs us the progress bar (helper treats
                # duration 0 as "no reporting") — never the render itself.
                pass

        # medium preset gives visually lossless quality; crf 18 is near-transparent
        # for re-encoded H.264. ultrafast/23 was the previous default and left
        # noticeable generation loss on high-res sources.
        _run_ffmpeg_with_progress(cmd, total_duration, progress_callback)
        return output_path
    finally:
        for p in temp_paths:
            os.remove(p)
