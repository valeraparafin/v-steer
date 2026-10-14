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


def test_lazy_packages_do_not_drag_test_suites_into_the_exe():
    """A collected test module pulls in pytest, pygments and Pillow: the exe doubled to 23 MB once."""
    import importlib
    import pkgutil

    for name in LAZY_PACKAGES:
        package = importlib.import_module(name)
        modules = [m.name for m in pkgutil.walk_packages(package.__path__, name + ".", onerror=lambda _n: None)]
        assert not [m for m in modules if ".test" in m or ".tests" in m], name
