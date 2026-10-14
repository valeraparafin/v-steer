"""Build dist/V-Steer.exe with PyInstaller, then run its --check. Called by build.cmd (and CI).

The packages to bundle come from vsteer.app.LAZY_PACKAGES, the same list --check proves.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vsteer.app import LAZY_PACKAGES  # after the sys.path line: run as a script, not installed


def pyinstaller_args() -> list[str]:
    args = [
        "--noconfirm", "--clean", "--onefile", "--console",
        "--name", "V-Steer",
        "--icon", str(ROOT / "packaging" / "v-steer.ico"),
        "--paths", str(ROOT / "src"),
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
    ]
    for package in LAZY_PACKAGES:
        args += ["--collect-submodules", package]
    return [*args, str(ROOT / "packaging" / "entry.py")]


def main() -> int:
    from PyInstaller.__main__ import run as pyinstaller_run

    pyinstaller_run(pyinstaller_args())
    # No stdin: after a failed check the exe asks "Press Enter", which would hang the build.
    return subprocess.call([str(ROOT / "dist" / "V-Steer.exe"), "--check"], stdin=subprocess.DEVNULL)


if __name__ == "__main__":
    raise SystemExit(main())
