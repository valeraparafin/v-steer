"""Write the V-Steer icon files; the drawing lives in src/vsteer/ui/icon.py (the READY look).

Regenerate after a design change (needs Pillow: pip install pillow):
    .venv\\Scripts\\python packaging\\make_icon.py
Writes packaging/v-steer.ico (exe icon), docs/icon.png and docs/tray/<state>.png (README).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vsteer.ui.icon import IconState, render  # after the src path above

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    images = [render(IconState.READY, size) for size in ICO_SIZES]
    largest = images[-1]
    largest.save(ROOT / "packaging" / "v-steer.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])
    render(IconState.READY, 128).save(ROOT / "docs" / "icon.png")
    tray = ROOT / "docs" / "tray"
    tray.mkdir(exist_ok=True)
    for state in IconState:  # the README's icon table; 48 px shown at 24 stays sharp on HiDPI
        render(state, 48).save(tray / f"{state.value}.png")


if __name__ == "__main__":
    main()
