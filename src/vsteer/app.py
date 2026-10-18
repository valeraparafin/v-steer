"""Entry point: python -m vsteer [--debug] [--config PATH] [--check] [--version]."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import importlib
import logging
import logging.handlers
import sys
import traceback
from ctypes import wintypes
from pathlib import Path

from . import __version__, config
from .session import Session
from .ui.console import ConsoleEvents

log = logging.getLogger("vsteer")

# Packages whose modules are imported by name at runtime, so PyInstaller cannot see them (plain
# imports, even inside functions, it does see). The one list for both: packaging/build.py bundles
# every submodule of each, and --check imports and exercises them.
LAZY_PACKAGES = (
    "bleak.backends.winrt",  # Windows backend only: the macOS/Linux ones cannot load here
    "winrt",
    "zeroconf",
)
_ERROR_ALREADY_EXISTS = 183
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def acquire_single_instance(name: str = "Local\\v-steer") -> int | None:
    handle = _kernel32.CreateMutexW(None, False, name)
    if not handle:
        return None
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return None
    return handle


def release_single_instance(handle: int) -> None:
    _kernel32.CloseHandle(handle)


def setup_logging(debug: bool, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    file = logging.handlers.RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(console)
    log.addHandler(file)


async def run(cfg: config.Config, cfg_path: Path) -> int:
    return await Session(cfg, cfg_path, ConsoleEvents()).run()


async def _smoke_runtime() -> None:
    """Build (not start) what the app uses from each lazy package; they load more on first use."""
    import ifaddr
    from bleak import BleakClient, BleakScanner
    from zeroconf.asyncio import AsyncZeroconf

    BleakScanner()  # WinRT scanner backend
    BleakClient("00:00:00:00:00:00")  # WinRT client backend; nothing connects
    zc = AsyncZeroconf(interfaces=["127.0.0.1"])
    await zc.async_close()
    ifaddr.get_adapters()


def check_runtime() -> int:
    """Load every lazily used dependency: proves an exe build is complete without Bluetooth."""
    missing = []
    for name in LAZY_PACKAGES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - report every broken module, not just the first
            missing.append(f"{name}: {exc}")
    if not missing:
        try:
            asyncio.run(_smoke_runtime())
        except Exception as exc:  # noqa: BLE001 - any failure here means the build is broken
            missing.append(f"runtime: {exc!r}")
    if missing:
        print("V-Steer check FAILED:")
        for line in missing:
            print(f"  {line}")
        return 1
    print(f"V-Steer {__version__} check OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v-steer", description="Steer in Zwift with a ThinkRider VS200.")
    parser.add_argument("--debug", action="store_true", help="log the full DirCon traffic")
    parser.add_argument("--config", type=Path, default=None, help="config file path")
    parser.add_argument("--check", action="store_true", help="check that Bluetooth and mDNS modules load, then exit")
    parser.add_argument("--version", action="version", version=f"V-Steer {__version__}")
    args = parser.parse_args(argv)
    if args.check:
        return check_runtime()
    cfg_path = args.config or config.default_path()
    setup_logging(args.debug, cfg_path.parent / "v-steer.log")
    log.info("V-Steer %s", __version__)

    handle = acquire_single_instance()
    if handle is None:
        log.error("V-Steer is already running.")
        return 1
    try:
        try:
            cfg = config.load(cfg_path)
        except config.ConfigError as exc:
            log.error("Config error: %s", exc)
            return 2
        return asyncio.run(run(cfg, cfg_path))
    except KeyboardInterrupt:
        log.info("Stopped.")
        return 0
    except Exception:
        log.exception("V-Steer stopped on an unexpected error (details in %s)", cfg_path.parent / "v-steer.log")
        return 1
    finally:
        release_single_instance(handle)


def _interactive() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def exe_main(argv: list[str] | None = None, *, pause=input) -> int:
    """Entry point of the .exe: after an error, keep a double-clicked console window open."""
    try:
        rc = main(argv)
    except SystemExit as exc:  # argparse: bad argument (2) or --version/--help (0)
        rc = exc.code if isinstance(exc.code, int) else int(exc.code is not None)
    except Exception:  # noqa: BLE001 - startup crash outside main's own handler: show it, then wait
        traceback.print_exc()
        rc = 1
    if rc and getattr(sys, "frozen", False) and _interactive():
        try:
            pause("Press Enter to close this window.")
        except (EOFError, KeyboardInterrupt):
            pass
    return rc
