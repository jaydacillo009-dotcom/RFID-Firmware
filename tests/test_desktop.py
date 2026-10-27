import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

from rfid_desktop import EventConsole, bridge_worker, desktop_config


class DesktopTest(unittest.TestCase):
    def test_worker_preserves_partial_frames_and_acknowledges_save_before_stop(self):
        stop, events = threading.Event(), queue.Queue()
        frame = {'id': 'ab' * 8, 'path': '/api/v1/commit',
                 'body': {'mode': 'borrow', 'student_uid': '01020304',
                          'item_uid': 'AABBCCDD', 'request_id': 'cd' * 16}}
        raw = b'@RFID:' + json.dumps(frame).encode() + b'\n'
        chunks = iter([raw[:10], b'', raw[10:]])

        class Device:
            writes = []
            closed = False
            def __enter__(self): return self
            def __exit__(self, *args): self.closed = True
            def read_until(self, *args, **kwargs): return next(chunks)
            def write(self, data): self.writes.append(data)

        device = Device()
        def submit(settings, path, body):
            self.assertEqual(body['request_id'], 'cd' * 16)
            stop.set()  # Disconnect requested while the API request is in flight.
            return 200, {'ok': True, 'student_name': 'Alice', 'item_name': 'Book'}

        with patch('rfid_desktop.submit_request', side_effect=submit):
            bridge_worker('COM3', {}, stop, events, lambda *a, **k: device)
        self.assertTrue(device.closed)
        self.assertEqual(len(device.writes), 1)
        self.assertEqual(json.loads(device.writes[0][6:])['id'], frame['id'])
        emitted = list(events.queue)
        self.assertEqual(emitted[0], ('connected', 'COM3'))
        self.assertEqual(emitted[-1], ('disconnected',))
        self.assertTrue(any(e[:2] == ('message', 'SAVED') for e in emitted))

    def test_uncertain_save_and_rejected_save_remain_distinct(self):
        events = queue.Queue()
        console = EventConsole(events)
        console.result('/api/v1/commit', {}, 503, {'ok': False, 'message': 'Offline'})
        console.result('/api/v1/commit', {}, 409, {'ok': False, 'message': 'Already borrowed'})
        self.assertEqual([event[1] for event in events.queue], ['UNCONFIRMED', 'FAILED'])

    def test_serial_failure_does_not_expose_secret_and_always_disconnects(self):
        events = queue.Queue()
        def fail(*args, **kwargs):
            raise OSError('sensitive-secret-value')
        bridge_worker('COM3', {}, threading.Event(), events, fail)
        emitted = list(events.queue)
        self.assertEqual(emitted[-1], ('disconnected',))
        self.assertEqual(emitted[0][:2], ('message', 'ERROR'))
        self.assertNotIn('sensitive-secret-value', str(emitted))

    def test_windows_settings_use_per_user_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ', {'LOCALAPPDATA': directory}):
                self.assertEqual(desktop_config(), Path(directory) / 'RFID Station' / 'rfid_config.json')


if __name__ == '__main__':
    unittest.main()
