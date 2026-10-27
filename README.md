# RFID Receive / Return station

All controls, RC522 RFID reading, red/green LEDs, and transaction logic run on
an ESP32. An Arduino Uno/classic Nano drives the 5V 16x2 I2C LCD. The ESP32
uses USB serial to the laptop, whose bridge calls the existing server API.

- ESP32 sketch: [RFID_Sender_ESP32.ino](RFID_Sender_ESP32/RFID_Sender_ESP32.ino)
  (keep `RFIDStation.h` beside it).
- Arduino LCD adapter: [RFID_Display_Arduino.ino](RFID_Display_Arduino/RFID_Display_Arduino.ino).
- [Complete wiring, upload, laptop bridge setup, and operation](RFID_WIRING.md).

Menu chooses Receive/Return, Scan starts, then tap student ID and item tag,
and press Scan again to save. Menu cancels before confirmation. The green LED
means the server confirmed a saved transaction; red indicates an error.

## Windows desktop app

The desktop app provides USB port selection, Receive / Return scan guidance,
server-confirmed save results, recent session activity, and an API settings page.
It uses the same signed API and scanner protocol as the CLI. No firmware changes
are needed. Scan and Menu actions still use the physical station buttons.

On Windows, install Python 3.9+ from python.org (include the Python launcher),
then double-click `start-windows.bat`. The first launch installs PySerial and
requires internet access. Choose **API settings**, enter your registered scanner
credentials, and save. On **Station**, select the ESP32 COM port and click
**Connect**. Close Arduino Serial Monitor and other bridge apps first.

To make a standalone Windows executable, double-click `build-windows.bat`
on a Windows PC. It installs the build dependencies and produces
`dist\RFID-Station.exe`, which can run without Python installed. Credentials
are not included in the build. The executable must be built and tested on Windows;
the Linux checkout does not contain a prebuilt Windows executable.

Desktop settings are stored in `%LOCALAPPDATA%\RFID Station\rfid_config.json`,
including the device secret. The app imports the existing CLI config on first
launch if available; **Save settings** stores its own per-user copy. Existing
`RFID_*` environment variables override saved values at startup. Activity is
limited to the latest 300 messages in memory and is cleared when the app closes.
Disconnect and close finish the current API request before releasing the port.
For an unconfirmed save, retry the same transaction using the station Scan button.

For development on any platform with Tk installed:

```sh
python -m pip install -r requirements-bridge.txt
python rfid_desktop.py
```

## Run the CLI

From this folder, run setup once:

```sh
./rfid --setup
```

Enter your API base URL, registered scanner device ID, and its secret (hidden
while typing). Settings are saved locally in `rfid_config.json`, excluded from
Git, with owner-only permissions on POSIX systems. You can also use the existing
`RFID_API_BASE_URL`, `RFID_DEVICE_ID`, and `RFID_DEVICE_SECRET_HEX` environment
variables instead of setup.

Close Arduino IDE Serial Monitor, then run:

```sh
./rfid --port /dev/ttyUSB1
```

Use `./rfid --list-ports` to find the ESP32. With one connected serial port,
`./rfid` selects it automatically; with several, it asks which one is the
ESP32. Leave the CLI running while scanning. Stop with Ctrl+C. Do not run the
old `laptop_bridge.py` at the same time.

The CLI reports scan progress, `[SAVED]` only after server-confirmed
saving, `[FAILED]` for rejection, and `[UNCONFIRMED]` for an uncertain save.
For an uncertain save, press the station's Scan button to retry the same
transaction after the connection is restored. Existing firmware is compatible;
no re-upload is needed for the CLI.

Requires Python 3.9+ and PySerial. If missing, install dependencies in a virtual
environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-bridge.txt
.venv/bin/python rfid_cli.py --setup
.venv/bin/python rfid_cli.py --port /dev/ttyUSB1
```

On Windows use `.venv\Scripts\python.exe` and a port such as `COM3`.
`--verbose` enables extra board diagnostics. Python environment/serial/API
failure messages are printed to the terminal; no API secret is printed.

## Accept student IDs as scanned

The station now accepts the first card locally as the student ID, then collects
a different item tag. It sends both UIDs to `/api/v1/commit` only when Scan is
pressed to confirm; it does not call the validation preview endpoint. Only
UID syntax is checked locally.

Re-upload the ESP32 sketch for this behavior. The currently deployed backend
now accepts arbitrary student UIDs on save after the
[backend update](backend_changes/README.md). The patch is now applied in the backend source, and the corrected Supabase
function has been deployed as active version 4. Receive/Return loan rules remain server-enforced at save time.

Older ESP32 firmware that requests student/item previews is also supported:
the CLI accepts those UIDs locally and sends no preview request to the API.
Item eligibility is checked at final commit. The latest API accepts missing student and item UIDs automatically. Receive/Return
loan rules still run at final commit. See `backend_changes/rfid-api/index.ts` for
the deployed source.

Student and item IDs no longer need prior registration. The API creates missing
rows on first successful use. The current deployed source and checkout-sync
instructions are in [backend_changes](backend_changes/README.md).
