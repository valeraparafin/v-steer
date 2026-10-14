import importlib.util
from pathlib import Path

from vsteer.app import LAZY_PACKAGES

ROOT = Path(__file__).resolve().parent.parent


def _build_module():
    spec = importlib.util.spec_from_file_location("v_steer_build", ROOT / "packaging" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _collected(args):
    return [args[i + 1] for i, a in enumerate(args) if a == "--collect-submodules"]


def test_the_exe_collects_exactly_the_lazy_packages():
    """#14: one list drives both what the exe bundles and what --check proves."""
    assert _collected(_build_module().pyinstaller_args()) == list(LAZY_PACKAGES)


def test_only_bleaks_windows_backend_is_bundled():
    """#15: the macOS/Linux backends cannot load on Windows; collecting them only adds warnings."""
    assert "bleak" not in _collected(_build_module().pyinstaller_args())
    assert "bleak.backends.winrt" in LAZY_PACKAGES


def _looks_like_tests(module: str) -> bool:
    last = module.rsplit(".", 1)[-1]
    return last.startswith(("test", "_test")) or last in ("conftest", "testing", "_testing")


def test_the_test_module_guard_catches_the_usual_names():
    assert _looks_like_tests("ifaddr.test_ifaddr")  # the one that doubled the exe
    assert _looks_like_tests("zeroconf._testing") and _looks_like_tests("pkg.tests.conftest")
    assert not _looks_like_tests("zeroconf.asyncio")


def test_lazy_packages_do_not_drag_test_suites_into_the_exe():
    """A collected test module pulls in pytest, pygments and Pillow: the exe doubled to 23 MB once."""
    import importlib
    import pkgutil

    for name in LAZY_PACKAGES:
        package = importlib.import_module(name)
        modules = [m.name for m in pkgutil.walk_packages(package.__path__, name + ".", onerror=lambda _n: None)]
        assert not [m for m in modules if _looks_like_tests(m)], name


def test_a_failing_check_does_not_wait_for_enter(monkeypatch):
    """Review: the frozen exe asks 'Press Enter' after an error; the build must not hang on it."""
    import subprocess
    import sys
    import types

    build = _build_module()
    calls = []
    fake_pyinstaller = types.ModuleType("PyInstaller.__main__")
    fake_pyinstaller.run = lambda args: None
    monkeypatch.setitem(sys.modules, "PyInstaller.__main__", fake_pyinstaller)
    monkeypatch.setattr(build.subprocess, "call", lambda cmd, **kw: calls.append(kw) or 1)
    assert build.main() == 1
    assert calls[0].get("stdin") is subprocess.DEVNULL
