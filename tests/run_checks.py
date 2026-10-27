"""Run the native firmware simulation and bridge contract tests (no real API writes)."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parent.parent
json_dir = Path(os.environ.get('ARDUINOJSON_INCLUDE', str(Path.home() / 'Arduino/libraries/ArduinoJson/src')))
if not (json_dir / 'ArduinoJson.h').is_file():
    sys.exit('Set ARDUINOJSON_INCLUDE to the src directory of ArduinoJson 7.x')
with tempfile.TemporaryDirectory(prefix='rfid-station-check-') as temp:
    executable = Path(temp) / 'station'
    capture = Path(temp) / 'frames.txt'
    subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                    '-I' + str(root / 'tests/stubs'), '-I' + str(json_dir),
                    str(root / 'tests/test_station.cpp'), '-o', str(executable)], check=True)
    subprocess.run([str(executable), str(capture)], check=True)
    display = Path(temp) / 'display'
    subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                    '-I' + str(root / 'tests/stubs'),
                    str(root / 'tests/test_display.cpp'), '-o', str(display)], check=True)
    subprocess.run([str(display)], check=True)
    env = dict(os.environ, RFID_FRAME_CAPTURE=str(capture), PYTHONDONTWRITEBYTECODE='1')
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                   cwd=root, env=env, check=True)
