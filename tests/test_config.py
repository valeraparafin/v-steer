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


def _old_config(appdata):
    old = appdata / "vs200-steer"
    old.mkdir()
    (old / "config.toml").write_text('[vs200]\naddress = "D3:F7:DD:C8:6A:69"\n', encoding="utf-8")
    (old / "vs200-steer.log").write_text("old log", encoding="utf-8")
    return old


def test_old_settings_move_to_the_new_folder(tmp_path):
    from vsteer.config import migrate_legacy_config

    old = _old_config(tmp_path)
    assert migrate_legacy_config(tmp_path) == old / "config.toml"
    assert "D3:F7:DD:C8:6A:69" in (tmp_path / "V-Steer" / "config.toml").read_text(encoding="utf-8")
    assert not (tmp_path / "V-Steer" / "vs200-steer.log").exists()  # old logs stay behind


def test_settings_move_even_if_the_new_folder_already_has_a_log(tmp_path):
    from vsteer.config import migrate_legacy_config

    _old_config(tmp_path)
    (tmp_path / "V-Steer").mkdir()
    (tmp_path / "V-Steer" / "v-steer.log").write_text("", encoding="utf-8")
    assert migrate_legacy_config(tmp_path) is not None
    assert (tmp_path / "V-Steer" / "config.toml").exists()


def test_existing_new_settings_are_left_alone(tmp_path):
    from vsteer.config import migrate_legacy_config

    _old_config(tmp_path)
    (tmp_path / "V-Steer").mkdir()
    (tmp_path / "V-Steer" / "config.toml").write_text("[vs200]\nswap = true\n", encoding="utf-8")
    assert migrate_legacy_config(tmp_path) is None
    assert "swap = true" in (tmp_path / "V-Steer" / "config.toml").read_text(encoding="utf-8")


def test_nothing_to_move_on_a_fresh_pc(tmp_path):
    from vsteer.config import migrate_legacy_config

    assert migrate_legacy_config(tmp_path) is None


def test_a_failed_move_does_not_stop_the_app(tmp_path, monkeypatch):
    from pathlib import Path

    from vsteer.config import migrate_legacy_config

    _old_config(tmp_path)

    def locked(self, target):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "replace", locked)
    assert migrate_legacy_config(tmp_path) is None


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


@pytest.mark.parametrize("value", ["D3:F7:DD:C8:6A", "D3-F7-DD-C8-6A-69", "D3:F7:DD:C8:6A:6G", "remote"])
def test_vs200_address_must_be_a_bluetooth_address(tmp_path, value):
    """#8: a typo in the address would make V-Steer search forever without saying why."""
    p = tmp_path / "config.toml"
    p.write_text(f'[vs200]\naddress = "{value}"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="vs200.address"):
        load(p)


def test_lowercase_bluetooth_address_is_fine(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[vs200]\naddress = "d3:f7:dd:c8:6a:69"\n', encoding="utf-8")
    assert load(p).vs200_address == "d3:f7:dd:c8:6a:69"


def test_unknown_keys_are_reported(tmp_path, caplog):
    """#8: a typo like pulse_mss must not be ignored silently."""
    import logging

    p = tmp_path / "config.toml"
    p.write_text("[steer]\npulse_mss = 300\n[stear]\npulse_ms = 300\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="vsteer"):
        load(p)
    assert "steer.pulse_mss" in caplog.text and "[stear]" in caplog.text


@pytest.mark.parametrize("name", ["KICKR 🚴 BIKE", 'Valera "V" Bike', "back\\slash"])
def test_any_device_name_survives_save_and_load(tmp_path, name):
    """#8: emoji were written as JSON surrogate pairs that TOML rejects on the next start."""
    p = tmp_path / "config.toml"
    save(Config(device_name=name), p)
    assert load(p).device_name == name


def test_settings_added_in_new_versions_appear_in_an_old_file(tmp_path):
    """#18: an old config.toml gains the new sections, and keeps the user's values."""
    p = tmp_path / "config.toml"
    p.write_text('[vs200]\naddress = "D3:F7:DD:C8:6A:69"\nswap = true\n', encoding="utf-8")
    load(p)
    text = p.read_text(encoding="utf-8")
    assert "[updates]" in text and "check = true" in text
    cfg = load(p)
    assert cfg.vs200_address == "D3:F7:DD:C8:6A:69" and cfg.swap is True


def test_a_complete_file_is_not_rewritten(tmp_path):
    p = tmp_path / "config.toml"
    save(Config(), p)
    p.write_text(p.read_text(encoding="utf-8") + "# my note\n", encoding="utf-8")
    load(p)
    assert "# my note" in p.read_text(encoding="utf-8")
