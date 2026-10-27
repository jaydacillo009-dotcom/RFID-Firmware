import hashlib
import hmac
import io
import json
import unittest
from unittest.mock import patch

from laptop_bridge import PREFIX, process_frame, signed_request


class BridgeTest(unittest.TestCase):
    def test_signs_exact_body_sent_to_api(self):
        body = {"mode": "borrow", "student_uid": "A1B2C3D4", "item_uid": None}
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            response = io.BytesIO(b'{"ok":true,"next":"scan_item"}')
            response.status = 200
            return response

        with patch("laptop_bridge.time.time", return_value=1700000000), \
             patch("laptop_bridge.secrets.token_hex", return_value="ab" * 16), \
             patch("laptop_bridge.urlopen", side_effect=fake_urlopen):
            status, result = signed_request("https://example.com/rfid-api", "scanner-1", bytes.fromhex("cd" * 32), "/api/v1/preview", body)

        request = captured["request"]
        signing = f"POST\n/api/v1/preview\n1700000000\n{'ab' * 16}\n{hashlib.sha256(request.data).hexdigest()}"
        expected = hmac.new(bytes.fromhex("cd" * 32), signing.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(request.get_header("X-signature"), expected)
        self.assertEqual(request.get_header("X-device-id"), "scanner-1")
        self.assertEqual(request.full_url, "https://example.com/rfid-api/api/v1/preview")
        self.assertEqual(json.loads(request.data), body)
        self.assertEqual((status, result["next"], captured["timeout"]), (200, "scan_item", 8))

    def test_serial_frame_forwards_and_correlates_response(self):
        frame = PREFIX + b'{"id":"1234567890abcdef","path":"/api/v1/commit","body":{"mode":"borrow"}}\n'
        calls = []

        def send(path, body):
            calls.append((path, body))
            return 409, {"ok": False, "message": "Already borrowed"}

        reply = process_frame(frame, send)
        self.assertEqual(calls, [("/api/v1/commit", {"mode": "borrow"})])
        self.assertEqual(json.loads(reply[len(PREFIX):]), {
            "id": "1234567890abcdef", "status": 409,
            "body": {"ok": False, "message": "Already borrowed"},
        })
        self.assertIsNone(process_frame(b"Scanner booted\n", send))
        self.assertEqual(len(calls), 1)

    def test_rejects_unknown_route_before_network(self):
        frame = PREFIX + b'{"id":"1234567890abcdef","path":"/bad","body":{}}\n'
        reply = process_frame(frame, lambda *_: self.fail("unexpected network call"))
        self.assertEqual(json.loads(reply[len(PREFIX):])["status"], 400)


if __name__ == "__main__":
    unittest.main()
