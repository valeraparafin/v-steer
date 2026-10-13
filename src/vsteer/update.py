"""Ask GitHub for the latest release once at start; never block or fail the ride over it."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from collections.abc import Callable

from . import __version__

log = logging.getLogger("vsteer")

REPO = "valeraparafin/v-steer"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
_LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"


def _parse(version: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in version.removeprefix("v").split("."))
    except ValueError:
        return None


def newer_version(latest_tag: str, current: str) -> str | None:
    """Return `latest_tag` if it is a higher version than `current`, else None."""
    latest, mine = _parse(latest_tag), _parse(current)
    if latest is None or mine is None:
        return None
    return latest_tag if latest > mine else None


def fetch_latest_tag(timeout: float = 5.0) -> str:
    request = urllib.request.Request(
        _LATEST_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"V-Steer/{__version__}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)["tag_name"]


async def check_for_update(current: str = __version__, *, fetch: Callable[[], str] = fetch_latest_tag) -> str | None:
    """The newer release tag, or None when up to date, offline or GitHub misbehaves."""
    try:
        tag = await asyncio.to_thread(fetch)
    except Exception as exc:  # noqa: BLE001 - no network, rate limit, bad JSON: just skip the check
        log.debug("update check skipped: %s", exc)
        return None
    return newer_version(tag, current)
