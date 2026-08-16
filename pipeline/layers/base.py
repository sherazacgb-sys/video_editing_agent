"""Shared plumbing for the layer system (see docs/plan.md).

A "layer" is anything drawn on top of the base video: a caption, a manual text
overlay, an image, later boxes/arrows/charts/PIP clips. Each layer module in
this package exposes two operations computed from the *same* layout pass, so
what gets drawn and what gets reported can never disagree (the root cause of
the original word-highlight drift bug was two independent layout guesses):

    draw(asset, ctx, t=None) -> PIL.Image   # RGBA, sized to the layer's own footprint
    bbox(asset, ctx, t=None) -> BBox        # where that footprint lands in output pixel space
"""

import os
from dataclasses import dataclass, field

# libass scans fontsdir non-recursively, so every bundled family's .ttf files
# are flattened into this one directory rather than living under per-family
# subfolders (those subfolders still exist under static/fonts/<Family>/ for the
# browser's @font-face rules, which don't have that restriction). Lives here
# (not overlay.py) so layer modules can use it without importing overlay.py,
# which imports them — that would be a circular import.
FONTS_DIR = os.path.join(
    # three dirname hops: base.py -> layers/ -> pipeline/ -> project root
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "static", "fonts", "bundled",
)

# Weight names treated as "bold" — must match the JS list in job_detail.html's
# drawFrame() so preview and export pick the same face for the same style dict.
BOLD_WEIGHTS = {"semibold", "bold", "extrabold", "black"}

_DEFAULT_FONT_FILE = "Roboto-Regular.ttf"


def font_file_for(style: dict) -> str:
    """Resolve a style dict to a bundled .ttf path for PIL text rendering and
    measurement. Mirrors the family-Weight.ttf naming convention every font
    under static/fonts/bundled/ already follows; falls back to Roboto Regular
    if the exact weight/style file isn't bundled for that family, since an
    approximate face is still far better than crashing the render."""
    family = (style.get('font') or 'Roboto').replace(' ', '')  # bundled files have no spaces in family names
    weight = (style.get('font_weight') or 'Regular').strip().lower()
    is_bold = weight in BOLD_WEIGHTS
    is_italic = bool(style.get('font_italic'))
    # Candidate order: exact match first, then progressively drop attributes,
    # so e.g. a family bundled without a BoldItalic file still gets its Bold face.
    if is_bold and is_italic:
        candidates = [f"{family}-BoldItalic.ttf", f"{family}-Bold.ttf", f"{family}-Regular.ttf"]
    elif is_bold:
        candidates = [f"{family}-Bold.ttf", f"{family}-Regular.ttf"]
    elif is_italic:
        candidates = [f"{family}-Italic.ttf", f"{family}-Regular.ttf"]
    else:
        candidates = [f"{family}-Regular.ttf"]
    for name in candidates:
        path = os.path.join(FONTS_DIR, name)
        if os.path.isfile(path):
            return path
    return os.path.join(FONTS_DIR, _DEFAULT_FONT_FILE)


@dataclass(frozen=True)
class LayerContext:
    """Render-target facts every layer type needs to lay itself out.
    Carries the *real* output frame size (after any resolution scaling), so
    layers position/scale against what ffmpeg will actually encode."""
    out_w: int
    out_h: int
    # Only animated layer types (charts, later) need a frame rate; None for
    # anything rendered as a static image per time-segment.
    fps: float | None = None


@dataclass(frozen=True)
class BBox:
    """Axis-aligned box in output pixel space, plus the frame size it was
    computed against so normalized (0-1) coords — the same space the asset
    `position` schema uses — can be derived without re-asking the context."""
    x0: float
    y0: float
    x1: float
    y1: float
    out_w: int
    out_h: int
    # Named sub-regions, e.g. "active_word" for a word-highlighted caption —
    # lets callers ask "box around the caption" vs "box around the current word".
    regions: dict = field(default_factory=dict)

    def normalized(self) -> tuple[float, float, float, float]:
        # 0-1 coords, consistent with the existing asset `position` schema.
        return (self.x0 / self.out_w, self.y0 / self.out_h,
                self.x1 / self.out_w, self.y1 / self.out_h)


def get_layer(asset_type: str):
    """Registry mapping an asset's `type` to its layer module. Import happens
    inside the function (not at module top) to avoid import cycles between
    base.py and the layer modules that import base.py. Phase 1 only registers
    captions/text; images, boxes, charts join in later phases (docs/plan.md)."""
    from pipeline.layers import caption
    return {
        'caption': caption,
        'text': caption,  # manual text overlays share the caption layout/render logic
    }.get(asset_type)
