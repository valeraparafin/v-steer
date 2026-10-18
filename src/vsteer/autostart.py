"""Start with Windows: a value under the current user's Run key (no admin rights needed)."""

from __future__ import annotations

import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "V-Steer"


def available() -> bool:
    """Only the exe has a stable path to start; a source checkout runs through run.cmd."""
    return bool(getattr(sys, "frozen", False))


def is_enabled(reg=winreg) -> bool:
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ) as key:
            reg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True


def enable(exe_path: str, reg=winreg) -> None:
    with reg.CreateKey(reg.HKEY_CURRENT_USER, RUN_KEY) as key:
        reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, f'"{exe_path}"')


def disable(reg=winreg) -> None:
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
            reg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass
