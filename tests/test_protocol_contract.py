"""Check captured firmware requests against the existing API/bridge contract."""
import json
import os
from pathlib import Path
import unittest
from laptop_bridge import PREFIX, process_frame

class ContractTest(unittest.TestCase):
    def test_firmware_frames_pass_through_bridge(self):
        capture = os.environ.get('RFID_FRAME_CAPTURE')
        if not capture:
            self.skipTest('Set RFID_FRAME_CAPTURE to the native firmware test output')
        frames = [line for line in Path(capture).read_bytes().splitlines() if line.startswith(PREFIX)]
        self.assertGreater(len(frames), 5)
        seen = set()
        ids = set()
        def api(path, body):
            seen.add(path)
            self.assertIn(body['mode'], ('borrow', 'return'))
            if path == '/api/v1/state':
                self.assertEqual(set(body), {'mode', 'stage'})
                self.assertIn(body['stage'], ('idle', 'scan_student', 'scan_item', 'confirm', 'success', 'error'))
            else:
                keys = {'mode', 'student_uid', 'item_uid'}
                if path.endswith('/commit'):
                    keys.add('request_id')
                    self.assertRegex(body['request_id'], r'^[0-9a-f]{32}$')
                    self.assertIsNotNone(body['item_uid'])
                self.assertEqual(set(body), keys)
                self.assertRegex(body['student_uid'], r'^([0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})$')
                if body['item_uid'] is not None:
                    self.assertRegex(body['item_uid'], r'^([0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})$')
            return 200, {'ok': True}
        for line in frames:
            frame = json.loads(line[len(PREFIX):])
            self.assertRegex(frame['id'], r'^[0-9a-f]{16}$')
            self.assertNotIn(frame['id'], ids)
            ids.add(frame['id'])
            reply = json.loads(process_frame(line, api)[len(PREFIX):])
            self.assertEqual(reply['id'], frame['id'])
            self.assertEqual(reply['status'], 200)
        self.assertEqual(seen, {'/api/v1/state', '/api/v1/commit'})
