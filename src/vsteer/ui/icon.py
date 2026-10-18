"""Draw the V-Steer icon for a tray state: a V between two steer arrows on a dark tile.

The looks of every state live in SCHEMES; ACTIVE_SCHEME picks the one the tray uses. The others
stay for comparing on a real taskbar.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PIL import Image, ImageDraw


class IconState(Enum):
    READY = "ready"  # remote and Zwift both connected
    PARTIAL = "partial"  # exactly one of them
    IDLE = "idle"  # neither
    ERROR = "error"  # steering is impossible


BACKGROUND = "#16181D"
WHITE = "#FFFFFF"
GREY_V = "#8B8F98"
ORANGE = "#FF7A1A"
GREY_ARROWS = "#6B6F78"
RED = "#E5484D"
YELLOW = "#F2C230"
GREEN = "#3FB950"


@dataclass(frozen=True)
class Look:
    v: str
    arrows: str
    outline: str | None = None
    dot: str | None = None


_NORMAL = Look(WHITE, ORANGE)
_GREY = Look(GREY_V, GREY_ARROWS)

SCHEMES: dict[str, dict[IconState, Look]] = {
    # Arrows change colour.
    "A": {IconState.READY: _NORMAL, IconState.PARTIAL: Look(WHITE, YELLOW),
          IconState.IDLE: Look(WHITE, GREY_ARROWS), IconState.ERROR: Look(WHITE, RED)},
    # Fixed icon plus a traffic-light dot.
    "B": {IconState.READY: Look(WHITE, ORANGE, dot=GREEN), IconState.PARTIAL: Look(WHITE, ORANGE, dot=YELLOW),
          IconState.IDLE: Look(WHITE, ORANGE, dot=GREY_V), IconState.ERROR: Look(WHITE, ORANGE, dot=RED)},
    # Colour or all grey; red arrows for errors.
    "C": {IconState.READY: _NORMAL, IconState.PARTIAL: _GREY, IconState.IDLE: _GREY,
          IconState.ERROR: Look(WHITE, RED)},
    # D' with a green outline when ready.
    "D": {IconState.READY: Look(WHITE, ORANGE, outline=GREEN), IconState.PARTIAL: Look(GREY_V, GREY_ARROWS, YELLOW),
          IconState.IDLE: _GREY, IconState.ERROR: Look(WHITE, RED, RED)},
    "D'": {IconState.READY: _NORMAL, IconState.PARTIAL: Look(GREY_V, GREY_ARROWS, YELLOW),
           IconState.IDLE: _GREY, IconState.ERROR: Look(WHITE, RED, RED)},
}
ACTIVE_SCHEME = "D'"

SUPERSAMPLE = 4
# Geometry on a 512 x 512 canvas.
V_POINTS = [(160, 128), (256, 392), (352, 128)]
LEFT_ARROW = [(112, 222), (64, 270), (112, 318)]
RIGHT_ARROW = [(400, 222), (448, 270), (400, 318)]
TILE_RADIUS = 112
DOT_CENTRE, DOT_RADIUS, DOT_RING = (420, 420), 72, 20


def _stroke(draw: ImageDraw.ImageDraw, points, width: float, colour: str, k: float) -> None:
    """Polyline with round caps and joins (Pillow lines have square ends)."""
    scaled = [(x * k, y * k) for x, y in points]
    draw.line(scaled, fill=colour, width=round(width * k), joint="curve")
    r = width * k / 2
    for x, y in scaled:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)


def _circle(draw: ImageDraw.ImageDraw, centre, radius: float, colour: str, k: float) -> None:
    x, y = centre[0] * k, centre[1] * k
    r = radius * k
    draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)


def render(state: IconState, size: int, scheme: str = ACTIVE_SCHEME) -> Image.Image:
    look = SCHEMES[scheme][state]
    # Thin strokes vanish at taskbar sizes: thicken them for the small images.
    v_width, arrow_width, outline_width = (84, 56, 48) if size <= 24 else (72, 46, 40) if size <= 48 else (64, 40, 32)
    canvas = size * SUPERSAMPLE
    k = canvas / 512
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    box = (0, 0, canvas - 1, canvas - 1)
    draw.rounded_rectangle(box, radius=round(TILE_RADIUS * k), fill=BACKGROUND)
    if look.outline:
        draw.rounded_rectangle(box, radius=round(TILE_RADIUS * k), outline=look.outline,
                               width=round(outline_width * k))
    _stroke(draw, V_POINTS, v_width, look.v, k)
    _stroke(draw, LEFT_ARROW, arrow_width, look.arrows, k)
    _stroke(draw, RIGHT_ARROW, arrow_width, look.arrows, k)
    if look.dot:
        _circle(draw, DOT_CENTRE, DOT_RADIUS + DOT_RING, BACKGROUND, k)
        _circle(draw, DOT_CENTRE, DOT_RADIUS, look.dot, k)
    return image.resize((size, size), Image.LANCZOS)
