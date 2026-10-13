import pytest

from vsteer.config import Config, ConfigError, load, save


def test_missing_file_is_created_with_defaults(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    cfg = load(path)
    assert cfg == Config()
    assert path.exists()
    assert load(path) == Config()


def test_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(vs200_address="D3:F7:DD:C8:6A:69", swap=True, pulse_ms=300,
                 device_name='My "Ride"', network_address="192.168.1.140")
    save(cfg, path)
    assert load(path) == cfg


def test_corrupt_file_raises_config_error_with_path(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[steer\npulse_ms = ", encoding="utf-8")
    with pytest.raises(ConfigError) as err:
        load(path)
    assert str(path) in str(err.value)


@pytest.mark.parametrize("value", ["10", "5000", '"fast"', "true"])
def test_pulse_ms_out_of_range_rejected(tmp_path, value):
    path = tmp_path / "config.toml"
    path.write_text(f"[steer]\npulse_ms = {value}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as err:
        load(path)
    assert "steer.pulse_ms" in str(err.value) and str(path) in str(err.value)


def test_swap_must_be_boolean(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[vs200]\nswap = "yes"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="vs200.swap"):
        load(path)


@pytest.mark.parametrize("value", ['"192.168.1.10:36866"', '"192.168.1"', '"lan"'])
def test_network_address_must_be_ipv4(tmp_path, value):
    path = tmp_path / "config.toml"
    path.write_text(f"[network]\naddress = {value}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="network.address"):
        load(path)


def test_valid_network_address_accepted(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[network]\naddress = "192.168.1.140"\n', encoding="utf-8")
    assert load(path).network_address == "192.168.1.140"


@pytest.mark.parametrize("value", ['""', '"' + "x" * 64 + '"'])
def test_device_name_must_fit_mdns(tmp_path, value):
    path = tmp_path / "config.toml"
    path.write_text(f"[zwift]\ndevice_name = {value}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="zwift.device_name"):
        load(path)


def test_section_must_be_a_table(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("steer = 300\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"\[steer\]"):
        load(path)


def test_old_settings_folder_moves_to_the_new_name(tmp_path):
    from vsteer.config import migrate_legacy_dir

    old = tmp_path / "vs200-steer"
    old.mkdir()
    (old / "config.toml").write_text('[vs200]\naddress = "D3:F7:DD:C8:6A:69"\n', encoding="utf-8")
    assert migrate_legacy_dir(tmp_path) == old
    assert not old.exists()
    assert "D3:F7:DD:C8:6A:69" in (tmp_path / "V-Steer" / "config.toml").read_text(encoding="utf-8")


def test_existing_new_folder_is_left_alone(tmp_path):
    from vsteer.config import migrate_legacy_dir

    (tmp_path / "vs200-steer").mkdir()
    (tmp_path / "V-Steer").mkdir()
    assert migrate_legacy_dir(tmp_path) is None
    assert (tmp_path / "vs200-steer").exists()


def test_nothing_to_move_on_a_fresh_pc(tmp_path):
    from vsteer.config import migrate_legacy_dir

    assert migrate_legacy_dir(tmp_path) is None


def test_a_locked_old_folder_does_not_stop_the_app(tmp_path, monkeypatch):
    from pathlib import Path

    from vsteer.config import migrate_legacy_dir

    (tmp_path / "vs200-steer").mkdir()

    def locked(self, target):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "rename", locked)
    assert migrate_legacy_dir(tmp_path) is None


def test_default_path_uses_the_new_folder(monkeypatch, tmp_path):
    from vsteer.config import default_path

    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert default_path() == tmp_path / "V-Steer" / "config.toml"


def test_update_check_is_on_by_default_and_can_be_turned_off(tmp_path):
    p = tmp_path / "config.toml"
    assert load(p).check_updates is True
    p.write_text("[updates]\ncheck = false\n", encoding="utf-8")
    assert load(p).check_updates is False


def test_saved_config_keeps_the_update_switch(tmp_path):
    p = tmp_path / "config.toml"
    save(Config(check_updates=False), p)
    assert load(p).check_updates is False
