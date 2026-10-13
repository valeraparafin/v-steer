"""PyInstaller entry point for V-Steer.exe (__main__.py uses a relative import)."""

from vsteer.app import exe_main

raise SystemExit(exe_main())
