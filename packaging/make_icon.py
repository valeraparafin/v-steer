"""Draw the V-Steer icon: a white V between two orange steer arrows on a dark tile.

Regenerate after a design change (needs Pillow: pip install pillow):
    .venv\\Scripts\\python packaging\\make_icon.py
Writes packaging/v-steer.ico (exe icon) and docs/icon.png (README).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BACKGROUND = "#16181D"
V_COLOUR = "#FFFFFF"
ARROW_COLOUR = "#FF7A1A"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPERSAMPLE = 4

# Geometry on a 512 x 512 canvas.
V_POINTS = [(160, 128), (256, 392), (352, 128)]
LEFT_ARROW = [(112, 222), (64, 270), (112, 318)]
RIGHT_ARROW = [(400, 222), (448, 270), (400, 318)]


def _stroke(draw: ImageDraw.ImageDraw, points, width: float, colour: str, k: float) -> None:
    """Polyline with round caps and joins (Pillow lines have square ends)."""
    scaled = [(x * k, y * k) for x, y in points]
    draw.line(scaled, fill=colour, width=round(width * k), joint="curve")
    r = width * k / 2
    for x, y in scaled:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)


def render(size: int) -> Image.Image:
    # Thin strokes vanish at taskbar sizes: thicken them for the small images.
    v_width, arrow_width = (84, 56) if size <= 24 else (72, 46) if size <= 48 else (64, 40)
    canvas = size * SUPERSAMPLE
    k = canvas / 512
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, canvas - 1, canvas - 1), radius=round(112 * k), fill=BACKGROUND)
    _stroke(draw, V_POINTS, v_width, V_COLOUR, k)
    _stroke(draw, LEFT_ARROW, arrow_width, ARROW_COLOUR, k)
    _stroke(draw, RIGHT_ARROW, arrow_width, ARROW_COLOUR, k)
    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    images = [render(size) for size in ICO_SIZES]
    largest = images[-1]
    largest.save(ROOT / "packaging" / "v-steer.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])
    render(128).save(ROOT / "docs" / "icon.png")


if __name__ == "__main__":
    main()
