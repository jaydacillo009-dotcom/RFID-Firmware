import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import rfid_cli as cli

SECRET = 'cd' * 32  # Test fixture only.


class CliTest(unittest.TestCase):
    def test_setup_saves_private_settings_without_printing_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'settings.json'
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), \
                    patch('builtins.input', side_effect=['', 'scanner-2']), \
                    patch('rfid_cli.getpass.getpass', return_value=SECRET), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(['--setup', '--config', str(config)]), 0)
            self.assertEqual(cli.load_config(config)['device_secret_hex'], SECRET)
            self.assertNotIn(SECRET, output.getvalue())
            if os.name == 'posix':
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_overrides_and_validation(self):
        saved = {'api_base_url': 'https://saved.example/api', 'device_id': 'saved',
                 'device_secret_hex': SECRET}
        args = SimpleNamespace(api_base_url='https://cli.example/', device_id=None)
        with patch.dict(os.environ, {'RFID_DEVICE_ID': 'environment'}, clear=True):
            resolved = cli.resolved_settings(args, saved)
        self.assertEqual(resolved['api_base_url'], 'https://cli.example')
        self.assertEqual(resolved['device_id'], 'environment')
        for url in ['http://example.com', 'https://user:pass@example.com', 'https://example.com/?key=x']:
            with self.assertRaises(ValueError):
                cli.validate_settings(dict(saved, api_base_url=url))

    def test_reports_success_only_for_commit(self):
        output = io.StringIO()
        console = cli.Console()
        request = {'mode': 'borrow', 'student_uid': '01020304', 'item_uid': 'AABBCCDD'}
        with contextlib.redirect_stdout(output):
            console.result('/api/v1/preview', request, 200, {'ok': True, 'item_name': 'Book'})
        self.assertIn('[READ]', output.getvalue())
        self.assertNotIn('[SAVED]', output.getvalue())
        with contextlib.redirect_stdout(output):
            console.result('/api/v1/commit', request, 200,
                           {'ok': True, 'student_name': 'Alice', 'item_name': 'Book'})
            console.result('/api/v1/commit', request, 409, {'ok': False, 'message': 'Already borrowed'})
            console.result('/api/v1/commit', request, 503, {'ok': False, 'message': 'Offline'})
        text = output.getvalue()
        self.assertEqual(text.count('[SAVED]'), 1)
        self.assertIn('[FAILED] Already borrowed', text)
        self.assertIn('[UNCONFIRMED]', text)
        self.assertIn('retry the same transaction', text)

    def test_serial_reassembles_timeout_fragments_and_recovers_after_oversize(self):
        chunks = iter([b'@RF', b'', b'ID:{"id":1}\n', b'x' * 4096, b'ignored\n', b'@RFID:ok\n'])
        device = SimpleNamespace(read_until=lambda *a, **k: next(chunks))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            lines = cli.serial_lines(device, cli.Console())
            self.assertEqual(next(lines), b'@RFID:{"id":1}\n')
            self.assertEqual(next(lines), b'@RFID:ok\n')
        self.assertIn('Oversized scanner message ignored', output.getvalue())

    def test_preview_is_local_and_never_checks_registration(self):
        with patch('rfid_cli.signed_request') as network:
            status, result = cli.submit_request({}, '/api/v1/preview', {
                'mode': 'borrow', 'student_uid': 'FFFFFFFF', 'item_uid': None})
            self.assertEqual(status, 200)
            self.assertEqual(result['next'], 'scan_item')
            status, result = cli.submit_request({}, '/api/v1/preview', {
                'mode': 'borrow', 'student_uid': 'FFFFFFFF', 'item_uid': 'AABBCCDD'})
            self.assertEqual((status, result['next']), (200, 'confirm'))
            network.assert_not_called()

    def test_port_selection_does_not_guess_between_boards(self):
        ports = [SimpleNamespace(device='/dev/ttyUSB0', description='Arduino'),
                 SimpleNamespace(device='/dev/ttyUSB1', description='ESP32')]
        self.assertEqual(cli.choose_port(ports, '/dev/ttyUSB1'), '/dev/ttyUSB1')
        with patch('sys.stdin.isatty', return_value=False), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'Multiple ports'):
                cli.choose_port(ports, None)

    def test_cli_serial_to_api_to_serial_and_terminal(self):
        try:
            import serial
        except ImportError:
            self.skipTest('Install pyserial for the CLI serial integration test')
        requests = [
            {'id': '01' * 8, 'path': '/api/v1/preview',
             'body': {'mode': 'borrow', 'student_uid': '01020304', 'item_uid': None}},
            {'id': '02' * 8, 'path': '/api/v1/commit',
             'body': {'mode': 'borrow', 'student_uid': '01020304', 'item_uid': 'AABBCCDD', 'request_id': 'ab' * 16}},
            {'id': '03' * 8, 'path': '/api/v1/commit',
             'body': {'mode': 'borrow', 'student_uid': 'FFFFFFFF', 'item_uid': 'AABBCCDD', 'request_id': 'ef' * 16}},
        ]
        chunks = iter([b'boot diagnostics\n'] + [b'@RFID:' + json.dumps(frame).encode() + b'\n' for frame in requests])
        class Device:
            writes = []
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read_until(self, *args, **kwargs):
                try: return next(chunks)
                except StopIteration: raise KeyboardInterrupt
            def write(self, data): self.writes.append(data)
        device = Device()
        results = [(200, {'ok': True, 'student_name': 'Alice', 'item_name': 'Book'}),
                   (404, {'ok': False, 'message': 'Student not registered'})]
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'settings.json'
            cli.save_config(config, {'api_base_url': 'https://example.com/api', 'device_id': 'scanner-1',
                                     'device_secret_hex': SECRET})
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), \
                    patch('serial.Serial', return_value=device) as connection, \
                    patch('serial.tools.list_ports.comports', return_value=[]), \
                    patch('rfid_cli.signed_request', side_effect=results) as api, \
                    contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(['--config', str(config), '--port', '/dev/ttyUSB1']), 0)
            connection.assert_called_once_with('/dev/ttyUSB1', 115200, timeout=1, write_timeout=2)
            self.assertEqual(api.call_count, 2)
            self.assertEqual(api.call_args_list[0].args[-1]['request_id'], 'ab' * 16)
            self.assertEqual([json.loads(line[6:])['id'] for line in device.writes], [r['id'] for r in requests])
            self.assertEqual(json.loads(device.writes[-1][6:])['status'], 404)
            text = output.getvalue()
            self.assertIn('[SAVED] RECEIVE successful', text)
            self.assertIn('[FAILED] Student not registered', text)
            self.assertNotIn('boot diagnostics', text)
            self.assertNotIn(SECRET, text)


if __name__ == '__main__':
    unittest.main()
