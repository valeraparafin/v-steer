import sys

from vsteer.autostart import RUN_KEY, VALUE_NAME, available, disable, enable, is_enabled


class FakeReg:
    """The part of winreg that autostart uses, over a dict; missing values raise like winreg."""

    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1
    KEY_READ = 0x20019
    KEY_SET_VALUE = 0x0002

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.keys: list[tuple] = []

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, path, reserved=0, access=KEY_READ):
        self.keys.append((root, path))
        return self._Key()

    def CreateKey(self, root, path):
        self.keys.append((root, path))
        return self._Key()

    def SetValueEx(self, key, name, reserved, kind, value):
        assert kind == self.REG_SZ
        self.values[name] = value

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        return self.values[name], self.REG_SZ

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        del self.values[name]


def test_enable_quotes_a_path_with_spaces():
    reg = FakeReg()
    enable(r"C:\Users\Valera Bike\Downloads\V-Steer.exe", reg)
    assert reg.values[VALUE_NAME] == r'"C:\Users\Valera Bike\Downloads\V-Steer.exe"' and is_enabled(reg)
    assert all(key == ("HKCU", RUN_KEY) for key in reg.keys)  # per user, no admin rights


def test_disable_removes_the_value():
    reg = FakeReg()
    enable(r"C:\V-Steer.exe", reg)
    disable(reg)
    assert not is_enabled(reg) and VALUE_NAME not in reg.values


def test_disable_twice_is_fine():
    reg = FakeReg()
    disable(reg)
    disable(reg)
    assert not is_enabled(reg)


def test_only_offered_in_the_exe(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert available() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert available() is True
