"""Caption layer: Pillow rendering + bbox for word-highlighted captions.

This module exists to fix the word-highlight drift bug (docs/plan.md): the old
export path measured word widths in PIL but let libass do the actual text
layout, so the highlight pill and the glyphs it sat behind were positioned by
two different engines and drifted apart. Here ONE engine (Pillow) both lays
out the text and draws the pill from that same layout, so they agree by
construction. The layout formulas (wrap width, line height, padding, pill
geometry) deliberately mirror job_detail.html's drawFrame() canvas code
line-for-line, so browser preview and ffmpeg export agree by construction too.

Plain (non-highlighted) captions are NOT handled here in Phase 1 — they keep
the existing libass/ASS path in pipeline/overlay.py, which is cheap and needs
no bbox precision since nothing else references their layout.
"""

import math
import os
import tempfile
from dataclasses import dataclass, field

from pipeline.layers.base import BBox, LayerContext, font_file_for

# Timeline segments shorter than this are dropped when splitting a caption into
# per-word-state intervals — guards against zero/negative-length slivers from
# touching or slightly overlapping whisper word timestamps.
_MIN_SEGMENT = 0.001

# Background box fills keyed by the `background` style value — same rgba values
# as _bgColor() in job_detail.html (0.6 alpha = 153/255), so a highlighted
# caption's background box looks the same in preview and export.
_BG_COLORS = {
    'dark': (0, 0, 0, 153),
    'light': (255, 255, 255, 153),
}


def is_dynamic(asset: dict) -> bool:
    """True when this asset must be rendered by this module (Pillow) instead of
    the ASS path: it needs per-word highlighting, which requires both per-word
    timestamps and a highlight color. Single source of truth used both to route
    assets in composite_overlay and to skip them in _write_ass_file, so an
    asset can never be rendered twice (or zero times) by disagreeing checks."""
    if asset.get('type') not in ('caption', 'text'):
        return False
    return bool(
        asset.get('style', {}).get('highlight_color')
        and asset.get('content', {}).get('words')
    )


@dataclass
class _Word:
    """One laid-out word: its text/timing from the asset plus the pixel slot
    the layout pass assigned it (left edge x, measured width, owning line)."""
    word: str
    start: float
    end: float
    width: float = 0.0
    x: float = 0.0
    line: int = 0


@dataclass
class _Layout:
    """Full layout result for one caption at output resolution — the single
    source of truth that draw(), bbox(), and render_overlays() all read from."""
    scaled: int          # font size in output pixels (style.font_size is calibrated to 1080p)
    line_h: float        # line height (scaled * 1.3, same factor as drawFrame)
    pad: float           # pill/background padding unit (scaled * 0.25, same as drawFrame)
    x_px: float          # block center x in output pixels (from position.x)
    y_px: float          # block center y in output pixels (from position.y)
    block_w: float       # widest line's width
    total_h: float       # len(lines) * line_h
    words: list[_Word] = field(default_factory=list)      # flat, in speech order
    line_widths: list[float] = field(default_factory=list)  # per-line pixel width
    line_ys: list[float] = field(default_factory=list)      # per-line center y
    font: object = None  # PIL ImageFont, kept so draw() measures with the same face


def _layout(asset: dict, ctx: LayerContext) -> _Layout:
    """Lay the caption's words out exactly like drawFrame() does in
    job_detail.html: same font-size scaling, same greedy wrap at 90% of frame
    width, same line-height/padding factors, same per-word cursor advance.
    Any change here must be mirrored in the JS (and vice versa) — the whole
    point is that the two implementations share one set of formulas."""
    from PIL import ImageFont

    style = asset.get('style', {})
    pos = asset.get('position', {'x': 0.5, 'y': 0.85})

    # font_size is calibrated to a 1080-tall frame (see drawFrame comment);
    # round() matches JS Math.round so both sides pick the identical pixel size.
    scaled = round(int(style.get('font_size', 72)) * ctx.out_h / 1080)
    font = ImageFont.truetype(font_file_for(style), scaled)

    line_h = scaled * 1.3
    pad = scaled * 0.25
    max_w = ctx.out_w * 0.9          # wrap threshold, same 90% as drawFrame's maxW
    space_w = font.getlength(' ')    # inter-word gap, measured not assumed

    # Greedy word-wrap identical to the JS: a word that would push the current
    # line past max_w starts a new line (but a single over-wide word still gets
    # placed — no mid-word breaking on either side).
    lines: list[list[_Word]] = []
    line_widths: list[float] = []
    cur: list[_Word] = []
    cur_w = 0.0
    for w in asset['content']['words']:
        w_w = font.getlength(w['word'])
        add_w = (space_w + w_w) if cur else w_w  # first word on a line has no leading space
        if cur and cur_w + add_w > max_w:
            lines.append(cur)
            line_widths.append(cur_w)
            cur = []
            cur_w = 0.0
        cur.append(_Word(word=w['word'], start=w['start'], end=w['end'], width=w_w))
        cur_w += (space_w + w_w) if len(cur) > 1 else w_w
    if cur:
        lines.append(cur)
        line_widths.append(cur_w)

    total_h = len(lines) * line_h
    block_w = max(line_widths)
    x_px = pos.get('x', 0.5) * ctx.out_w
    y_px = pos.get('y', 0.85) * ctx.out_h

    # Assign each word its pixel slot: lines are stacked centered on y_px,
    # words flow left-to-right from each line's centered left edge.
    flat: list[_Word] = []
    line_ys: list[float] = []
    for i, ln in enumerate(lines):
        line_y = y_px - total_h / 2 + line_h * i + line_h / 2
        line_ys.append(line_y)
        cx = x_px - line_widths[i] / 2
        for word in ln:
            word.x = cx
            word.line = i
            cx += word.width + space_w
            flat.append(word)

    return _Layout(
        scaled=scaled, line_h=line_h, pad=pad,
        x_px=x_px, y_px=y_px, block_w=block_w, total_h=total_h,
        words=flat, line_widths=line_widths, line_ys=line_ys, font=font,
    )


def _pill_rect(lay: _Layout, word: _Word) -> tuple[float, float, float, float]:
    """Highlight pill rectangle for one word, in output pixels — the exact
    formula drawFrame() uses (rx/ry/rw/rh), expressed as x0,y0,x1,y1. Shared
    by draw() and bbox() so the drawn pill and the reported region are always
    the same rectangle."""
    x0 = word.x - lay.pad * 0.5
    y0 = lay.line_ys[word.line] - lay.line_h / 2 + lay.pad * 0.15
    return (x0, y0, x0 + word.width + lay.pad, y0 + lay.line_h - lay.pad * 0.3)


def _active_index(lay: _Layout, t: float) -> int | None:
    """Which word is being spoken at t (half-open interval, same `start <= t <
    end` test as the JS) — None between words or outside all word spans."""
    for i, w in enumerate(lay.words):
        if w.start <= t < w.end:
            return i
    return None


def bbox(asset: dict, ctx: LayerContext, t: float = None) -> BBox:
    """Whole-block bbox in output pixel space, with an "active_word" sub-region
    (the pill rectangle) when t falls inside a specific word's span. t defaults
    to the asset's start so callers who don't care about word timing still get
    a meaningful answer."""
    lay = _layout(asset, ctx)
    if t is None:
        t = asset['start']
    regions = {}
    idx = _active_index(lay, t)
    if idx is not None:
        px0, py0, px1, py1 = _pill_rect(lay, lay.words[idx])
        regions['active_word'] = BBox(px0, py0, px1, py1, ctx.out_w, ctx.out_h)
    return BBox(
        lay.x_px - lay.block_w / 2, lay.y_px - lay.total_h / 2,
        lay.x_px + lay.block_w / 2, lay.y_px + lay.total_h / 2,
        ctx.out_w, ctx.out_h, regions=regions,
    )


def _draw_state(lay: _Layout, style: dict, ctx: LayerContext, active_idx: int | None):
    """Render the caption with word `active_idx` highlighted (or none) onto a
    transparent RGBA image sized to the caption's own footprint. Returns
    (image, (left, top)) where left/top is the image's top-left corner in
    output pixel coordinates — everything drawn is symmetric about the block
    center, so placement is just center minus half the image size."""
    from PIL import Image, ImageDraw

    background = style.get('background')
    has_bg = bool(background) and background != 'none'

    # Outline/shadow only when there's no background box, mirroring the ASS
    # styles this replaces (Default has Outline 4 + Shadow 3; the BG styles
    # use the box itself for contrast). Both are specified in 1080p units like
    # font_size, so scale them the same way.
    stroke = 0 if has_bg else max(1, round(4 * ctx.out_h / 1080))
    shadow = 0 if has_bg else max(1, round(3 * ctx.out_h / 1080))

    # Canvas must cover the background box (block + pad on every side — a
    # superset of the pill's pad*0.5 per-word overhang) plus stroke/shadow
    # bleed, with a couple px of slack against antialiasing clipping.
    margin = stroke + shadow + 2
    img_w = math.ceil(lay.block_w + 2 * lay.pad) + 2 * margin
    img_h = math.ceil(lay.total_h + lay.pad) + 2 * margin
    # Top-left corner in output coords: the drawing is symmetric about the
    # block center both ways (bg box, pills, and lines all center on it).
    left = round(lay.x_px - img_w / 2)
    top = round(lay.y_px - img_h / 2)

    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def ox(x: float) -> float:
        return x - left   # output-space x -> image-space x

    def oy(y: float) -> float:
        return y - top    # output-space y -> image-space y

    # Corner radius: drawFrame uses a fixed 6 CSS px, which only equals 6
    # output px when the preview canvas is itself 1080 tall — scale by output
    # height so export matches what preview shows at full-size playback.
    radius = max(2, round(6 * ctx.out_h / 1080))

    if has_bg:
        # Whole-block background box, same rect formula as drawFrame's bg path.
        bg_fill = _BG_COLORS.get(background, background)  # dark/light -> rgba tuple, else pass CSS color through
        bx0 = ox(lay.x_px - lay.block_w / 2 - lay.pad)
        by0 = oy(lay.y_px - lay.total_h / 2 - lay.pad * 0.5)
        draw.rounded_rectangle(
            [bx0, by0, bx0 + lay.block_w + 2 * lay.pad, by0 + lay.total_h + lay.pad],
            radius=radius, fill=bg_fill,
        )

    color = style.get('color', '#FFFFFF')
    highlight = style.get('highlight_color')
    for i, w in enumerate(lay.words):
        wx, wy = ox(w.x), oy(lay.line_ys[w.line])
        if i == active_idx and highlight:
            # Pill first so the word paints on top of its own highlight —
            # same layering the old ASS path enforced with Layer 0/Layer 1.
            px0, py0, px1, py1 = _pill_rect(lay, w)
            draw.rounded_rectangle(
                [ox(px0), oy(py0), ox(px1), oy(py1)],
                radius=radius, fill=highlight,
            )
        if shadow:
            # Drop-shadow pass: glyph+outline copy offset down-right in
            # translucent black (alpha 170 ≈ the ASS BackColour &H55 the old
            # Default style used), drawn before the real glyph so it sits under.
            draw.text(
                (wx + shadow, wy + shadow), w.word, font=lay.font, anchor='lm',
                fill=(0, 0, 0, 170), stroke_width=stroke, stroke_fill=(0, 0, 0, 170),
            )
        # anchor='lm' = left edge, vertical middle — the PIL equivalent of the
        # JS textAlign='left' + textBaseline='middle' the preview uses.
        draw.text(
            (wx, wy), w.word, font=lay.font, anchor='lm',
            fill=color, stroke_width=stroke, stroke_fill=(0, 0, 0, 255),
        )

    return img, (left, top)


def draw(asset: dict, ctx: LayerContext, t: float = None):
    """Layer interface: the caption as it appears at time t (which word, if
    any, carries the highlight pill), as a transparent RGBA image sized to the
    caption's own footprint. t defaults to the asset's start, matching bbox()."""
    lay = _layout(asset, ctx)
    if t is None:
        t = asset['start']
    img, _origin = _draw_state(lay, asset.get('style', {}), ctx, _active_index(lay, t))
    return img


def render_overlays(asset: dict, ctx: LayerContext) -> list[dict]:
    """Pre-render every distinct visual state of this caption (one per
    highlighted word, plus a single shared no-highlight state for the gaps
    before/between/after words) as temp PNGs, and return the overlay steps
    composite_overlay needs: [{'path', 'x', 'y', 'enable'}, ...].

    One PNG per *state* (not per frame): the pill only changes at word
    boundaries, so a handful of stills with `between(t,..)` enable windows is
    exact, and avoids paying Python per-frame compositing cost (the hybrid
    trade-off in docs/plan.md). Caller owns deleting the temp files."""
    lay = _layout(asset, ctx)
    style = asset.get('style', {})
    start, end = asset['start'], asset['end']

    # Walk the caption's time range in word order, splitting it into segments
    # each tagged with the active word index (or None for gaps). The cursor
    # clamps overlapping/out-of-order whisper timestamps so segments never
    # overlap — ffmpeg would happily draw two states at once otherwise.
    segments: list[tuple[float, float, int | None]] = []
    cursor = start
    for idx, w in enumerate(lay.words):
        if cursor >= end:
            break
        if w.start > cursor:
            segments.append((cursor, min(w.start, end), None))  # gap before this word
            cursor = min(w.start, end)
        seg_start, seg_end = max(w.start, cursor), min(w.end, end)
        if seg_end > seg_start:
            segments.append((seg_start, seg_end, idx))
            cursor = seg_end
    if cursor < end:
        segments.append((cursor, end, None))  # tail after the last word ends

    # Group segments by state so each distinct image is rendered/encoded once;
    # a state active in several windows just gets a summed enable expression
    # (between() returns 0/1, so + is logical OR here).
    by_state: dict[int | None, list[tuple[float, float]]] = {}
    for s, e, idx in segments:
        if e - s < _MIN_SEGMENT:
            continue  # drop zero-length slivers from touching timestamps
        by_state.setdefault(idx, []).append((s, e))

    items = []
    for idx, windows in by_state.items():
        img, (left, top) = _draw_state(lay, style, ctx, idx)
        # Temp PNG fed to ffmpeg as an overlay input; caller cleans up after encode.
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        img.save(path, "PNG")
        enable = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in windows)
        items.append({'path': path, 'x': left, 'y': top, 'enable': enable})
    return items
