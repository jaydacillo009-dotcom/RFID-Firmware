# ESP32 Receive / Return station with Arduino LCD adapter

The ESP32 owns the RFID reader, both buttons, buzzer, LEDs, and transaction flow.
The Arduino Uno R3/classic Nano powers and drives the 5V LCD. The ESP32 connects
to the laptop by USB; the laptop calls the existing server API. No ESP32 Wi-Fi
credentials or API secrets belong in firmware.

`../RFID-Backend` was not present. The existing API and bridge were found in
`../RFID-Device-BACKEND`. This project's `laptop_bridge.py` reuses that repository's HMAC-signed API
protocol, with optional CLI result reporting added.

## Wiring

Disconnect USB while wiring. ESP32 pin numbers below mean GPIO numbers on a
classic ESP32 DevKit, not ESP32-C3/S3 or Nano ESP32 board pin labels.

| Component | Pin / terminal | Connect to |
|---|---|---|
| RC522 | VCC / 3.3V | ESP32 3V3 (never 5V) |
| RC522 | GND | ESP32 GND |
| RC522 | SDA / SS | ESP32 GPIO5 |
| RC522 | SCK | ESP32 GPIO18 |
| RC522 | MOSI | ESP32 GPIO23 |
| RC522 | MISO | ESP32 GPIO19 |
| RC522 | RST | ESP32 GPIO27 (unchanged) |
| RC522 | IRQ | Leave disconnected |
| Scan button | Two switched terminals | ESP32 GPIO25 and GND |
| Menu button | Two switched terminals | ESP32 GPIO26 and GND |
| Small passive piezo | Positive | ESP32 GPIO14 |
| Small passive piezo | Negative | ESP32 GND |
| Green LED | Anode / long leg | ESP32 GPIO32 through its own 330-ohm resistor |
| Green LED | Cathode / short leg | ESP32 GND |
| Red LED | Anode / long leg | ESP32 GPIO33 through its own 330-ohm resistor |
| Red LED | Cathode / short leg | ESP32 GND |
| ESP32 | GPIO17 | Arduino D2 |
| ESP32 | GND | Arduino GND |
| Arduino | D3 | Leave disconnected (unused 5V transmit output) |
| LCD | VCC | Arduino 5V |
| LCD | GND | Arduino GND |
| LCD | SDA | Arduino A4 |
| LCD | SCL | Arduino A5 |

Power both boards through their own USB connections. ESP32 USB must connect to
the laptop running the bridge. Arduino USB may connect to the same laptop for
power. Leave the boards' 5V and 3V3 pins disconnected from each other.

Move any buttons or buzzer previously attached to Arduino D4/D5/D6 to the ESP32
pins above. The LCD stays on the Arduino; no I2C level shifter is needed in this
arrangement. The ESP32-to-Arduino display connection is one-way, at 9600 baud.

Buttons use internal pull-ups, so no external resistors are needed. On a
four-leg button use terminals that connect only when pressed, not a pair
already permanently connected. Each LED needs its own series resistor.

The default buzzer configuration is for a small low-current passive piezo
connected directly to GPIO14. For an active-HIGH buzzer MODULE, set
`ACTIVE_BUZZER = true` in `RFIDStation.h`, connect GPIO14 to its signal input,
and power it according to its rating. A speaker, siren, or high-current
bare buzzer needs an appropriate transistor driver, not direct GPIO power.

## Upload

1. Open `RFID_Sender_ESP32/RFID_Sender_ESP32.ino` in Arduino IDE. Keep
   `RFIDStation.h` in the same folder. Install **esp32 by Espressif Systems**
   in Boards Manager, and **MFRC522** plus **ArduinoJson 7.x** in Library Manager.
   Select **ESP32 Dev Module** and its actual USB port, then upload.
2. Open `RFID_Display_Arduino/RFID_Display_Arduino.ino`. Install
   **LiquidCrystal I2C** (the version with `lcd.init()`). Select **Arduino Uno**
   or your classic Nano variant and its USB port, then upload. If the LCD has
   power but no text, adjust its contrast screw and check whether its I2C
   address is `0x3F` instead of `0x27`.
3. Close the ESP32 Serial Monitor and start the laptop bridge. Stop the bridge
   before uploading ESP32 firmware again. Only one program can own its port.

A PlatformIO configuration for the ESP32 is also provided in `platformio.ini`:
`pio run` builds and `pio run -t upload` uploads. The LCD-only sketches in
`LCD_*` are standalone diagnostics, not the main application.

## Run the CLI (recommended)

Run `./rfid --setup` once, then `./rfid --port /dev/ttyUSB1`. Setup prompts for
API URL, device ID, and the existing scanner secret without displaying the
secret. The CLI saves local settings and reports accepted scans and confirmed
saves or failures. Use `./rfid --list-ports` to find the ESP32. Close Serial
Monitor first and run only one bridge app. See the root README for dependency
installation and Windows commands. No firmware change is needed for this CLI.

## Start the basic laptop bridge (alternative)

The laptop requires internet access and Python 3.9 or newer. From this project:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-bridge.txt
```

Set the API base URL and the credentials of a scanner already enrolled in the
server's `devices` table. Replace the placeholders; keep the secret private.
For the existing Supabase deployment documented by the backend:

```sh
export RFID_API_BASE_URL='https://edelmgnzwcngnozaxrsx.supabase.co/functions/v1/rfid-api'
export RFID_DEVICE_ID='scanner-1'
export RFID_DEVICE_SECRET_HEX='<your existing 64-character scanner secret>'
.venv/bin/python -m serial.tools.list_ports
.venv/bin/python laptop_bridge.py --port /dev/ttyUSB0
```

Use the ESP32's actual port, not the Arduino LCD adapter's port. For a Render
host, set `RFID_API_BASE_URL` to `https://<your-service>.onrender.com` without
`/rfid-api`; the bridge appends `/api/v1/...`.

The backend's existing environment can be reused instead of creating a new one:

```sh
../RFID-Device-BACKEND/.venv/bin/python laptop_bridge.py --port /dev/ttyUSB0
```

On Windows, use `py -3 -m venv .venv`, `.venv\Scripts\python.exe` instead of
`.venv/bin/python`, set variables with PowerShell `$env:NAME='value'`, and use
a port such as `COM3`. The bridge reads environment variables; it does not
automatically load `.env` files.

The device ID and secret must match server enrollment. Student IDs and item
tags are accepted as scanned; the API creates missing rows automatically at
save time. See `backend_changes/README.md` for deployed source and synchronization.
Receive/Return loan rules still apply.

## Operation

1. **Menu** toggles **Receive / Return** while idle. Receive is the default.
   The existing API calls student receipt of equipment `borrow`, so Receive
   sends `mode: "borrow"`; Return sends `mode: "return"`.
2. **Scan** starts a transaction. Tap a student card and remove it. The station
   accepts its UID immediately without calling the API to check the student.
3. Tap an item RFID tag and remove it. Both UIDs are now collected locally.
   The student card cannot be used as the item tag. No preview calls are made.
4. When both UIDs are read, press **Scan** again. The laptop sends
   `POST /api/v1/commit`, where item and borrow/return rules are checked.
   Only a successful API response shows **Successful!**
   and lights the **green LED**. The display returns to the menu after 3 seconds.
5. **Menu** cancels before confirmation. No transaction is posted when cancelled.

The **red LED** and low beep indicate rejection, connection failure, or wrong
card. LEDs clear when the next scan/button action starts; green is reserved for
server-confirmed saves. Button presses are debounced and holding a button
counts as one press. Early Scan presses cannot skip a card-reading step.

After confirmation, the server may already have saved the record; Menu cannot
undo it. If the save outcome is uncertain, restore the laptop connection and
press **Scan** to retry. The firmware reuses the same request ID so the API
returns the original result without another loan. It journals this pending
request in ESP32 flash before sending, allowing recovery even if opening the
laptop serial port resets the board. On recovery it shows **Recover last save /
SCAN to retry**. Do not erase ESP32 flash while recovering an uncertain save.
A definite API rejection allows cancellation; ambiguous outcomes require retry.

The server also receives coalesced `POST /api/v1/state` updates for its kiosk.
The firmware performs USB/API waits without blocking button processing. There
is no offline transaction queue: saving requires the laptop bridge and server;
reading the cards is local. The API secret and HTTPS signing stay on the laptop.

This firmware assumes an **RC522/MFRC522 reader** with compatible ISO14443A tags.
13.56 MHz alone does not establish compatibility with a student card or phone.

## Verification

Run `python3 tests/run_checks.py` with g++ and ArduinoJson 7.x installed. By
default it finds headers at `~/Arduino/libraries/ArduinoJson/src`; otherwise
set `ARDUINOJSON_INCLUDE` to the library's `src` directory.

Checks exercise the actual ESP32 workflow against mocked pins/serial/NVS,
the Arduino LCD frame parser, and the real laptop bridge with mocked HTTPS.
They cover immediate student UID acceptance without preview requests, mode
mapping, sequence enforcement, cancellation, rejected/uncertain commits, reboot
recovery, duplicate-safe retry, timeouts, reply correlation, overlong frames,
API payload fields, HMAC signing, and LED success only after an API save.
No test sends live API writes.

Both sketches were compiled locally for their target architectures: ESP32 Dev
Module (PlatformIO / Arduino ESP32 2.0.17) and Arduino Uno (ATmega328P). Actual
hardware uploads and live authenticated API calls have not been performed.
