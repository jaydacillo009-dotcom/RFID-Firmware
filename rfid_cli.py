"""Listen to an ESP32 over USB, forward scans to the API, and show results."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlsplit

from laptop_bridge import process_frame, signed_request

DEFAULT_API = 'https://edelmgnzwcngnozaxrsx.supabase.co/functions/v1/rfid-api'
DEFAULT_CONFIG = Path(__file__).resolve().with_name('rfid_config.json')


def validate_settings(settings):
    url = urlsplit(settings.get('api_base_url', ''))
    if (url.scheme != 'https' or not url.netloc or url.query or url.fragment
            or url.username is not None or url.password is not None):
        raise ValueError('API URL must be HTTPS, without credentials, query, or fragment.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', settings.get('device_id', '')):
        raise ValueError('Device ID must be 1–64 letters, digits, underscores, or hyphens.')
    if not re.fullmatch(r'[0-9a-fA-F]{64}', settings.get('device_secret_hex', '')):
        raise ValueError('Device secret must be the existing 64-character hex scanner secret.')
    return settings


def load_config(path):
    try:
        with path.open(encoding='utf-8') as source:
            value = json.load(source)
    except FileNotFoundError:
        return {}
    except (ValueError, UnicodeError):
        raise ValueError(f'Invalid configuration file: {path}. Run ./rfid --setup again.') from None
    if not isinstance(value, dict) or any(not isinstance(v, str) for v in value.values()):
        raise ValueError(f'Invalid configuration file: {path}. Run ./rfid --setup again.')
    return value


def save_config(path, settings):
    """Replace atomically, with owner-only permissions on POSIX."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.rfid-config-', delete=False) as target:
            temporary = Path(target.name)
            json.dump(settings, target, indent=2)
            target.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def configure(path):
    try:
        existing = load_config(path)
    except ValueError:
        existing = {}
        print("Replacing invalid configuration with new settings.")
    api = existing.get('api_base_url', os.getenv('RFID_API_BASE_URL') or DEFAULT_API)
    device = existing.get('device_id', os.getenv('RFID_DEVICE_ID') or 'scanner-1')
    print('Use the device ID and secret already registered on your API.')
    settings = {
        'api_base_url': (input(f'API base URL [{api}]: ').strip() or api).rstrip('/'),
        'device_id': input(f'Device ID [{device}]: ').strip() or device,
    }
    previous_secret = existing.get('device_secret_hex', os.getenv('RFID_DEVICE_SECRET_HEX', ''))
    prompt = 'Device secret (hidden; Enter keeps existing): ' if previous_secret else 'Device secret (hidden): '
    settings['device_secret_hex'] = getpass.getpass(prompt).strip() or previous_secret
    validate_settings(settings)
    save_config(path, settings)
    print(f'Settings saved to {path}. The secret is not printed.')


def resolved_settings(args, saved):
    return validate_settings({
        'api_base_url': (args.api_base_url or os.getenv('RFID_API_BASE_URL')
                         or saved.get('api_base_url', DEFAULT_API)).rstrip('/'),
        'device_id': args.device_id or os.getenv('RFID_DEVICE_ID') or saved.get('device_id', ''),
        'device_secret_hex': os.getenv('RFID_DEVICE_SECRET_HEX') or saved.get('device_secret_hex', ''),
    })


def submit_request(settings, path, body):
    # Older flashed firmware asks for previews. Accept captured UIDs locally;
    # only the final commit is a transaction request to the API.
    if path == '/api/v1/preview':
        uid_pattern = r'(?:[0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})'
        student, item = body.get('student_uid'), body.get('item_uid')
        if (body.get('mode') not in ('borrow', 'return')
                or not isinstance(student, str) or not re.fullmatch(uid_pattern, student)
                or (item is not None and (not isinstance(item, str) or not re.fullmatch(uid_pattern, item)))):
            return 400, {'ok': False, 'message': 'Invalid scanned UID or mode'}
        result = {'ok': True, 'student_name': student, 'next': 'confirm' if item else 'scan_item'}
        if item:
            result['item_name'] = item
        return 200, result
    return signed_request(settings['api_base_url'], settings['device_id'],
                          bytes.fromhex(settings['device_secret_hex']), path, body)


def choose_port(ports, requested):
    if requested:
        return requested
    if len(ports) == 1:
        return ports[0].device
    if not ports:
        raise ValueError('No USB serial ports detected. Connect the ESP32 with a data USB cable.')
    print('Choose the ESP32 port, not the Arduino LCD adapter:')
    for i, port in enumerate(ports, 1):
        print(f'  {i}. {port.device} — {port.description}')
    if not sys.stdin.isatty():
        raise ValueError('Multiple ports detected. Specify --port, for example --port /dev/ttyUSB1.')
    try:
        index = int(input('ESP32 port number: ')) - 1
    except ValueError:
        raise ValueError('Enter one of the displayed port numbers.') from None
    if not 0 <= index < len(ports):
        raise ValueError('Port number is out of range.')
    return ports[index].device


class Console:
    def __init__(self):
        self.last_state = None

    def show(self, label, text):
        # Server-provided names/messages must stay on one readable terminal line.
        text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(text))
        text = ''.join(c for c in text if c.isprintable() or c.isspace())
        print(f'{time.strftime("%H:%M:%S")} [{label}] {" ".join(text.split())}', flush=True)

    def result(self, path, request, status, response):
        ok = status == 200 and response.get('ok') is True
        if not ok:
            reason = response.get('message') or f'API returned HTTP {status}'
            if path == '/api/v1/commit' and not (400 <= status < 500 and status not in (408, 429)):
                self.show('UNCONFIRMED', f'{reason}. Save outcome unknown; press Scan to retry the same transaction.')
            else:
                self.show('FAILED', f'{reason} (HTTP {status})')
            return
        if path == '/api/v1/preview':
            if request.get('item_uid'):
                name = response.get('item_name') or 'Item'
                self.show('READ', f'{name} captured locally. Press Scan to confirm and save.')
            else:
                name = response.get('student_name') or 'Student'
                self.show('READ', f'{name} captured locally. Tap the item RFID tag.')
        elif path == '/api/v1/commit':
            mode = 'RETURN' if request.get('mode') == 'return' else 'RECEIVE'
            student = response.get('student_name') or 'Student'
            item = response.get('item_name') or 'item'
            self.show('SAVED', f'{mode} successful — {student} / {item}')
        elif path == '/api/v1/state':
            state = (request.get('mode'), request.get('stage'))
            if state != self.last_state:
                mode = 'RETURN' if state[0] == 'return' else 'RECEIVE'
                if state[1] == 'idle':
                    self.show('READY', f'{mode} mode. Press Scan to start; Menu changes mode.')
                elif state[1] == 'scan_student':
                    self.show('SCAN', f'{mode}: tap the student ID.')
                elif state[1] == 'scan_item':
                    self.show('READ', 'Student ID captured. Tap the item RFID tag.')
                elif state[1] == 'confirm':
                    self.show('READY', 'Both IDs captured. Press Scan to save.')
                self.last_state = state


def serial_lines(device, console):
    """Keep partial frames across serial read timeouts; discard oversized lines."""
    buffer = bytearray()
    dropping = False
    while True:
        chunk = device.read_until(b'\n', size=4096)
        if not chunk:
            continue
        if not dropping:
            buffer.extend(chunk)
            if len(buffer) >= 4096:
                console.show('WARNING', 'Oversized scanner message ignored.')
                buffer.clear()
                dropping = True
        if chunk.endswith(b'\n'):
            if not dropping:
                yield bytes(buffer)
            buffer.clear()
            dropping = False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true', help='Save API URL, device ID and secret once')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG, help='Path to private settings JSON')
    parser.add_argument('--port', help='ESP32 USB port, e.g. /dev/ttyUSB1 or COM3; auto-selects a single port')
    parser.add_argument('--list-ports', action='store_true', help='List USB serial ports and exit')
    parser.add_argument('--api-base-url', help='Override API base URL')
    parser.add_argument('--device-id', help='Override registered device ID')
    parser.add_argument('--verbose', action='store_true', help='Also show ESP32 diagnostic lines and HTTP statuses')
    args = parser.parse_args(argv)
    console = Console()
    try:
        if args.setup:
            configure(args.config.expanduser().resolve())
            return 0
        try:
            import serial
            from serial.tools import list_ports
        except ImportError:
            parser.error('Install PySerial: python3 -m pip install -r requirements-bridge.txt')
        ports = sorted(list_ports.comports(), key=lambda port: port.device)
        if args.list_ports:
            for port in ports:
                print(f'{port.device} — {port.description}')
            if not ports:
                print('No USB serial ports detected.')
            return 0
        saved = load_config(args.config.expanduser())
        try:
            settings = resolved_settings(args, saved)
        except ValueError as error:
            parser.error(f'{error} Run ./rfid --setup first, or set RFID_API_BASE_URL, RFID_DEVICE_ID and RFID_DEVICE_SECRET_HEX.')
        port = choose_port(ports, args.port)
        def send(path, body):
            return submit_request(settings, path, body)
        try:
            with serial.Serial(port, 115200, timeout=1, write_timeout=2) as device:
                console.show('CONNECTED', f'ESP32 on {port}. Keep this app running. Ctrl+C stops it.')
                for line in serial_lines(device, console):
                    reply = process_frame(line, send, verbose=args.verbose, on_result=console.result)
                    if reply is not None:
                        device.write(reply)
        except serial.SerialException:
            console.show('ERROR', f'Cannot use {port}. Check USB and port permissions; close Arduino Serial Monitor or other bridge apps. Then rerun this command.')
            return 1
    except KeyboardInterrupt:
        print('\nStopped.', flush=True)
        return 0
    except EOFError:
        console.show('ERROR', 'Input ended. Run setup in a terminal, or specify --port explicitly.')
        return 1
    except (ValueError, OSError) as error:
        console.show('ERROR', str(error))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
