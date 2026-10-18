"""Build dist/V-Steer.exe with PyInstaller, then run its --check. Called by build.cmd (and CI).

The packages and modules to bundle come from vsteer.app.LAZY_PACKAGES and LAZY_MODULES, the same
lists --check proves. The exe is windowed (the tray); --console opens its own window.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vsteer.app import LAZY_MODULES, LAZY_PACKAGES  # after the sys.path line: run as a script, not installed

# Pillow extensions the tray never uses (it draws lines and saves ICO/PNG); AVIF alone is 8 MB.
# Pillow imports each of them lazily and copes when they are missing; --check proves ICO still works.
EXCLUDED_MODULES = ("PIL._avif", "PIL._webp", "PIL._imagingft", "PIL._imagingcms", "PIL._imagingtk",
                    "PIL.ImageTk", "PIL.ImageQt", "tkinter")


def pyinstaller_args() -> list[str]:
    args = [
        "--noconfirm", "--clean", "--onefile", "--noconsole",
        "--name", "V-Steer",
        "--icon", str(ROOT / "packaging" / "v-steer.ico"),
        "--paths", str(ROOT / "src"),
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
    ]
    for package in LAZY_PACKAGES:
        args += ["--collect-submodules", package]
    for module in LAZY_MODULES:
        args += ["--hidden-import", module]
    for module in EXCLUDED_MODULES:
        args += ["--exclude-module", module]
    return [*args, str(ROOT / "packaging" / "entry.py")]


def main() -> int:
    from PyInstaller.__main__ import run as pyinstaller_run

    pyinstaller_run(pyinstaller_args())
    # No stdin: after a failed check the exe asks "Press Enter", which would hang the build.
    return subprocess.call([str(ROOT / "dist" / "V-Steer.exe"), "--check"], stdin=subprocess.DEVNULL)


if __name__ == "__main__":
    raise SystemExit(main())
