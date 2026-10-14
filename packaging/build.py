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
    import PyInstaller.__main__

    PyInstaller.__main__.run(pyinstaller_args())
    return subprocess.call([str(ROOT / "dist" / "V-Steer.exe"), "--check"])


if __name__ == "__main__":
    raise SystemExit(main())
