"""PyInstaller entry point for vs200-steer.exe (__main__.py uses a relative import)."""

from vs200steer.app import exe_main

raise SystemExit(exe_main())
