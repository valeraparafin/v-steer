# vs200-steer

Steer in Zwift with a ThinkRider VS200 thumb remote: tap `+` to move right, `−` to move left.

vs200-steer connects to a VS200 over Bluetooth and shows up in Zwift as a Zwift Ride controller
over your local network (the same way Wi-Fi trainers do). Your other VS200 can keep shifting
through the trainer as before.

## Requirements

- Windows 10/11 with Bluetooth
- Python 3.11+ (until the .exe release)
- Zwift on this PC, or on another device on the same network

## Setup

    git clone https://github.com/valeraparafin/vs200-steer.git
    cd vs200-steer
    .\setup.cmd

## Run

    .\run.cmd

First run: wake the VS200 you want to steer with and press any button — its address is saved to
`%APPDATA%\vs200-steer\config.toml`. Then in Zwift: **Paired Devices → Controls** → pair
**KICKR BIKE PRO 1337** (Wi-Fi icon). Zwift shows "Welcome to steering".

## Config

`%APPDATA%\vs200-steer\config.toml`:

| key | default | meaning |
|-----|---------|---------|
| `vs200.address` | (first run) | which remote to use |
| `vs200.swap` | `false` | `true` makes `+` steer left |
| `steer.pulse_ms` | `200` | how long one tap holds the D-pad (50..2000) |
| `zwift.device_name` | `KICKR BIKE PRO 1337` | name shown in Zwift |
| `network.address` | (auto) | LAN IPv4 to advertise, if auto-detection picks the wrong one |

## Troubleshooting

- **Zwift doesn't list the device**: allow Python (later: vs200-steer.exe) through Windows Firewall
  when asked, including Public networks; make sure Zwift and this PC are on the same network; if
  you use a VPN, set `network.address` to your LAN IP.
- **Zwift on another device (Apple TV, tablet) and a VPN on this PC**: VPNs that route all traffic
  through the tunnel often block the local network too; disconnect the VPN while riding.
- **VS200 not found**: press a button to wake it (it sleeps after ~30 min); make sure it is not
  connected to the trainer or another app.
- **Something odd**: run `.\run.cmd --debug` and look at `%APPDATA%\vs200-steer\vs200-steer.log`.

## Credits

DirCon server derived from [ZwiftBridge](https://github.com/amirlagasse/ZwiftBridge) (MIT).
Protocol knowledge from [BikeControl](https://github.com/OpenBikeControl/bikecontrol). See NOTICE.
