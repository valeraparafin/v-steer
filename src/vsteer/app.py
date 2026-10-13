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

from . import __version__, config, net
from .core import Core
from .ui.console import ConsoleUI
from .vs200 import Vs200Input, pick_remote
from .zwift.ride import EmulatorState, RideEmulator

log = logging.getLogger("vsteer")

HINT_AFTER_S = 60
# Loaded lazily at runtime, so a frozen build can miss them; --check imports them up front.
RUNTIME_MODULES = (
    "bleak",
    "bleak.backends.winrt.scanner",
    "bleak.backends.winrt.client",
    "zeroconf",
    "zeroconf.asyncio",
    "ifaddr",
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


def should_hint(state: EmulatorState, elapsed_s: float, hinted: bool) -> bool:
    return not hinted and elapsed_s >= HINT_AFTER_S and state is EmulatorState.ADVERTISING


def setup_logging(debug: bool, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    file = logging.handlers.RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(console)
    log.addHandler(file)


async def _hint_loop(emulator: RideEmulator) -> None:
    loop = asyncio.get_running_loop()
    started, hinted = loop.time(), False
    while not hinted:
        await asyncio.sleep(5)
        if should_hint(emulator.state, loop.time() - started, hinted):
            hinted = True
            log.warning(
                "Zwift has not connected yet. In Zwift: Paired Devices -> Controls -> pair '%s'. "
                "If it is not listed: allow V-Steer/Python through Windows Firewall, "
                "check the PC and Zwift are on the same network, or set [network] address in the config.",
                emulator.advertised_name,
            )


async def run(cfg: config.Config, cfg_path: Path) -> int:
    if not cfg.vs200_address:
        log.info("First run: wake the VS200 you want to steer with and press any button on it ...")
        address = await pick_remote(timeout=120)
        if not address:
            log.error("No VS200 was pressed within 2 minutes. Is it awake and not connected to the trainer?")
            return 2
        cfg.vs200_address = address
        config.save(cfg, cfg_path)
        log.info("Saved VS200 %s to %s", address, cfg_path)

    lan = cfg.network_address or net.pick_address(net.list_adapters(), net.default_route_ip())
    if not lan:
        log.error("No LAN address found to advertise on. Set [network] address in %s", cfg_path)
        return 2

    emulator = RideEmulator(lan, device_name=cfg.device_name)
    core = Core(cfg, emulator)
    core.subscribe(ConsoleUI().on_status)
    emulator.on_state_change = core.on_emulator_state
    vs200 = Vs200Input(cfg.vs200_address, on_tap=core.on_tap, on_state=core.on_input_state)

    await emulator.start()
    log.info("Advertising '%s' on %s:%d. In Zwift: Paired Devices -> Controls -> pair it.",
             emulator.advertised_name, lan, emulator.bound_port)
    hint = asyncio.create_task(_hint_loop(emulator))
    try:
        await vs200.run()
    finally:
        hint.cancel()
        await emulator.stop()
    return 0


async def _smoke_runtime() -> None:
    """Build (not start) a BLE scanner and an mDNS stack: WinRT and zeroconf load more on first use."""
    from bleak import BleakScanner
    from zeroconf.asyncio import AsyncZeroconf

    BleakScanner()
    zc = AsyncZeroconf(interfaces=["127.0.0.1"])
    await zc.async_close()


def check_runtime() -> int:
    """Load every lazily used dependency: proves an exe build is complete without Bluetooth."""
    missing = []
    for name in RUNTIME_MODULES:
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
    moved_from = None if args.config else config.migrate_legacy_dir()
    cfg_path = args.config or config.default_path()
    setup_logging(args.debug, cfg_path.parent / "v-steer.log")
    log.info("V-Steer %s", __version__)
    if moved_from:
        log.info("Moved settings from %s to %s", moved_from, cfg_path.parent)

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
