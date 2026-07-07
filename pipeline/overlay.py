import subprocess
import os
import tempfile

# libass scans fontsdir non-recursively, so every bundled family's .ttf files
# are flattened into this one directory rather than living under per-family
# subfolders (those subfolders still exist under static/fonts/<Family>/ for the
# browser's @font-face rules, which don't have that restriction).
_FONTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static", "fonts", "bundled",
)

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
    return f"\\c&H{b}{g}{r}&".upper()


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


def _build_image_filter_complex(image_assets: list[dict], out_w: int, out_h: int, sub_filter: str, scale_filter: str | None) -> str:
    # Builds a filter_complex graph: base video -> one overlay step per image
    # (in layer order) -> subtitles burned in last, so captions/text always stay
    # readable on top of any images.
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

    parts.append(f"{current}{sub_filter}[outv]")
    return ";".join(parts)


def composite_overlay(
    video_path: str,
    assets: list[dict],
    output_path: str,
    resolution: str = 'original',
) -> str:
    ass_path = _write_ass_file(assets)
    styled_image_paths = []  # temp PNGs from _style_image, cleaned up in finally
    try:
        ass_ffmpeg = ass_path.replace("\\", "/").replace(":", "\\:")
        fonts_ffmpeg = _FONTS_DIR.replace("\\", "/").replace(":", "\\:")

        sub_filter = f"subtitles='{ass_ffmpeg}':fontsdir='{fonts_ffmpeg}'"
        height = _RESOLUTION_HEIGHTS.get(resolution)
        # scale=-2:H preserves aspect ratio and ensures width is even (libx264 requirement).
        scale_filter = f"scale=-2:{height}" if height else None

        image_assets = [a for a in sorted(assets, key=lambda a: a.get('layer', 1)) if a.get('type') == 'image']

        if not image_assets:
            # No images on the timeline — keep the original single -vf path
            # (simpler command, unchanged from before image overlays existed).
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
            from pipeline.captions import _get_aspect_ratio
            src_w, src_h = _get_aspect_ratio(video_path)
            if height:
                out_h = height
                # Same even-width rounding ffmpeg's scale=-2:H applies, computed here
                # in Python so image overlay sizes can be calculated against the real output width.
                out_w = round(src_w * out_h / src_h / 2) * 2
            else:
                out_w, out_h = src_w, src_h

            filter_complex = _build_image_filter_complex(image_assets, out_w, out_h, sub_filter, scale_filter)

            cmd = ["ffmpeg", "-y", "-i", video_path]
            for asset in image_assets:
                styled_path = _style_image(asset['content']['path'], asset.get('style', {}))
                if styled_path:
                    styled_image_paths.append(styled_path)
                cmd += ["-i", styled_path or asset['content']['path']]
            cmd += [
                "-filter_complex", filter_complex,
                "-map", "[outv]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "copy",
                output_path,
            ]

        # medium preset gives visually lossless quality; crf 18 is near-transparent
        # for re-encoded H.264. ultrafast/23 was the previous default and left
        # noticeable generation loss on high-res sources.
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
        return output_path
    finally:
        os.remove(ass_path)
        for p in styled_image_paths:
            os.remove(p)
