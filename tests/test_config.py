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
