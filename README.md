# V-Steer

Steer in Zwift with a ThinkRider VS200 thumb remote: tap `+` to move right, `−` to move left.
Your other VS200 keeps shifting through the trainer as before.

## You need

- A Windows 10/11 PC with Bluetooth.
- A second VS200 that is **not** connected to the trainer.
- Zwift on this PC, or on another device on the same network.

## First run

1. Download `V-Steer.exe` from [Releases](https://github.com/valeraparafin/v-steer/releases/latest).
2. Run it. If Windows says it protected your PC, click **More info → Run anyway**.
3. If Windows Firewall asks, click **Allow** (Private networks is enough).
4. Wake the steering VS200 and press any button on it. The app remembers this remote.
5. In Zwift: **Paired Devices → Controls** → pick **KICKR BIKE PRO 1337**.
   Zwift says "Welcome to steering".
6. Ride: `+` moves you one step right, `−` one step left.

Keep the window open while you ride; close it to stop.

## Every next ride

Run `V-Steer.exe`, then start Zwift. If Zwift doesn't connect by itself, pair
**KICKR BIKE PRO 1337** under **Controls** again.

## Settings

Open `%APPDATA%\V-Steer\config.toml` in Notepad, then restart the app.

| setting | default | what it does |
|---------|---------|--------------|
| `swap` | `false` | `true`: `+` steers left |
| `pulse_ms` | `200` | how long one tap holds the steer (50..2000) |
| `address` under `[vs200]` | your remote | clear it (`""`) to pick a different remote |
| `device_name` | `KICKR BIKE PRO 1337` | the name shown in Zwift |
| `address` under `[network]` | auto | your PC's LAN IP, if Zwift can't find the app |

## Troubleshooting

- **Zwift doesn't list KICKR BIKE PRO 1337**: Windows may treat your home Wi-Fi as a Public
  network, where the app is blocked. Set it to Private (Settings → Network & internet → your
  network → Private network). Zwift and this PC must be on the same network. With a VPN on,
  disconnect it or set `[network] address`.
- **The remote isn't found**: press a button to wake it (it sleeps after ~30 min). It must not be
  connected to the trainer or another app.
- **The antivirus deletes the exe**: this is a known false alarm for unsigned Python apps; restore
  it from quarantine or [report it](https://github.com/valeraparafin/v-steer/issues).

## Report a problem

[Open an issue](https://github.com/valeraparafin/v-steer/issues/new) and attach
`%APPDATA%\V-Steer\v-steer.log`.

## More

- [How it works, running from source, building](docs/how-it-works.md)
- Credits: [ZwiftBridge](https://github.com/amirlagasse/ZwiftBridge) (MIT),
  [BikeControl](https://github.com/OpenBikeControl/bikecontrol). See [NOTICE](NOTICE).
- License: [MIT](LICENSE)
