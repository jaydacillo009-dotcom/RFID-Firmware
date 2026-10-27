"""RFID Station desktop bridge. Run with Python or build on Windows."""
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from laptop_bridge import process_frame
from rfid_cli import (Console, DEFAULT_API, DEFAULT_CONFIG, load_config, save_config,
                      serial_lines, submit_request, validate_settings)


def desktop_config():
    """Keep packaged settings in a writable per-user location."""
    base = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.config'))
    return base / 'RFID Station' / 'rfid_config.json'


class EventConsole(Console):
    def __init__(self, events):
        super().__init__()
        self.events = events

    def show(self, label, text):
        self.events.put(('message', label, str(text)))

    def result(self, path, request, status, response):
        super().result(path, request, status, response)
        if path == '/api/v1/state' and status == 200 and response.get('ok') is True:
            self.events.put(('stage', request.get('mode'), request.get('stage')))


class StopRequested(Exception):
    pass


def bridge_worker(port, settings, stop, events, serial_factory=None):
    """All serial and network work stays off the Tk event thread."""
    console = EventConsole(events)
    try:
        if serial_factory is None:
            import serial
            serial_factory = serial.Serial
        with serial_factory(port, 115200, timeout=0.25, write_timeout=2) as device:
            class Reader:
                def read_until(self, *args, **kwargs):
                    if stop.is_set():
                        raise StopRequested()
                    return device.read_until(*args, **kwargs)

            events.put(('connected', port))
            for line in serial_lines(Reader(), console):
                reply = process_frame(
                    line, lambda path, body: submit_request(settings, path, body),
                    verbose=False, on_result=console.result)
                if reply is not None:
                    # Finish acknowledging an in-flight save before disconnecting.
                    device.write(reply)
    except StopRequested:
        pass
    except ImportError:
        console.show('ERROR', 'PySerial is missing. Install requirements-bridge.txt first.')
    except Exception:
        # OS errors can contain sensitive request details; use a safe UI message.
        console.show('ERROR', 'Connection interrupted. Check USB, close Serial Monitor, '
                     'and reconnect. If a save was in progress, its outcome may be '
                     'unknown; retry the same transaction with the station Scan button.')
    finally:
        events.put(('disconnected',))


class StationApp:
    BG = '#f3f5f9'
    INK = '#18263c'
    MUTED = '#64748b'
    BLUE = '#245be8'

    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.closing = False
        self.connected = False
        self.config_path = desktop_config()
        self.port_map = {}
        self.saved_count = 0
        root.title('RFID Station')
        root.geometry('1020x760')
        root.minsize(820, 650)
        root.configure(bg=self.BG)
        self._styles()
        self.port = tk.StringVar()
        self.api = tk.StringVar(value=DEFAULT_API)
        self.device_id = tk.StringVar(value='scanner-1')
        self.secret = tk.StringVar()
        self.status = tk.StringVar(value='Disconnected')
        self.mode = tk.StringVar(value='RECEIVE / RETURN')
        self.headline = tk.StringVar(value='Connect your scanner')
        self.hint = tk.StringVar(value='Choose the ESP32 USB port below, then select Connect.')
        self.count = tk.StringVar(value='0 confirmed saves this session')
        self._layout()
        self._load_settings()
        self.refresh_ports()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self._poll)

    def _styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background=self.BG, foreground=self.INK)
        style.configure('TFrame', background=self.BG)
        style.configure('Card.TFrame', background='white')
        style.configure('TLabel', background=self.BG)
        style.configure('Card.TLabel', background='white')
        style.configure('Muted.TLabel', foreground=self.MUTED)
        style.configure('Title.TLabel', font=('Segoe UI', 24, 'bold'))
        style.configure('Hero.TLabel', font=('Segoe UI', 21, 'bold'), background='white')
        style.configure('TButton', padding=(14, 9))
        style.configure('Primary.TButton', background=self.BLUE, foreground='white')
        style.map('Primary.TButton', background=[('active', '#1948c4'), ('disabled', '#adb9d0')])
        style.configure('TEntry', padding=8, fieldbackground='white')
        style.configure('TCombobox', padding=7, fieldbackground='white')
        style.configure('TNotebook', borderwidth=0)
        style.configure('TNotebook.Tab', padding=(20, 10))
        style.configure('Treeview', rowheight=30, background='white', fieldbackground='white')
        style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'), padding=8)

    def _layout(self):
        outer = ttk.Frame(self.root, padding=28)
        outer.pack(fill='both', expand=True)
        header = ttk.Frame(outer)
        header.pack(fill='x', pady=(0, 20))
        ttk.Label(header, text='RFID Station', style='Title.TLabel').pack(side='left')
        self.badge = tk.Label(header, textvariable=self.status, bg='#e2e8f0',
                              fg=self.MUTED, padx=14, pady=8, font=('Segoe UI', 10, 'bold'))
        self.badge.pack(side='right')
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill='both', expand=True)
        station = ttk.Frame(self.tabs, padding=(0, 20))
        settings = ttk.Frame(self.tabs, padding=24)
        self.tabs.add(station, text='Station')
        self.tabs.add(settings, text='API settings')
        self.settings_tab = settings

        connection = ttk.Frame(station)
        connection.pack(fill='x', pady=(0, 18))
        ttk.Label(connection, text='ESP32 USB port').pack(side='left', padx=(0, 10))
        self.ports = ttk.Combobox(connection, textvariable=self.port, state='readonly', width=31)
        self.ports.pack(side='left', fill='x', expand=True)
        self.refresh_button = ttk.Button(connection, text='Refresh', command=self.refresh_ports)
        self.refresh_button.pack(side='left', padx=8)
        self.connect_button = ttk.Button(connection, text='Connect', style='Primary.TButton',
                                         command=self.toggle_connection)
        self.connect_button.pack(side='left')

        hero = ttk.Frame(station, style='Card.TFrame', padding=24)
        hero.pack(fill='x')
        ttk.Label(hero, textvariable=self.mode, style='Card.TLabel',
                  foreground=self.BLUE, font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        ttk.Label(hero, textvariable=self.headline, style='Hero.TLabel').pack(anchor='w', pady=(10, 8))
        ttk.Label(hero, textvariable=self.hint, style='Card.TLabel', wraplength=730).pack(anchor='w')
        steps = ttk.Frame(hero, style='Card.TFrame')
        steps.pack(fill='x', pady=(24, 0))
        self.steps = []
        for index, title in enumerate(('Start', 'Student ID', 'Item tag', 'Confirm')):
            label = tk.Label(steps, text=f'{index + 1}   {title}', bg='#eef2f7', fg=self.MUTED,
                             padx=12, pady=10, font=('Segoe UI', 10, 'bold'))
            label.pack(side='left', fill='x', expand=True, padx=(0, 6))
            self.steps.append(label)

        activity_header = ttk.Frame(station)
        activity_header.pack(fill='x', pady=(22, 10))
        ttk.Label(activity_header, text='Recent activity', font=('Segoe UI', 12, 'bold')).pack(side='left')
        ttk.Label(activity_header, textvariable=self.count, style='Muted.TLabel').pack(side='right')
        activity = ttk.Frame(station)
        activity.pack(fill='both', expand=True)
        self.history = ttk.Treeview(activity, columns=('time', 'result', 'detail'), show='headings', height=6)
        for key, title, width in [('time', 'Time', 80), ('result', 'Status', 125), ('detail', 'Details', 580)]:
            self.history.heading(key, text=title)
            self.history.column(key, width=width, minwidth=60, stretch=key == 'detail')
        scroll = ttk.Scrollbar(activity, orient='vertical', command=self.history.yview)
        self.history.configure(yscrollcommand=scroll.set)
        self.history.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.history.tag_configure('SAVED', foreground='#15803d')
        self.history.tag_configure('FAILED', foreground='#b91c1c')
        self.history.tag_configure('ERROR', foreground='#b91c1c')
        self.history.tag_configure('UNCONFIRMED', foreground='#a16207')
        ttk.Label(station, text='Use the buttons on the station: Menu selects Receive / Return; Scan starts and confirms.',
                  style='Muted.TLabel', wraplength=850).pack(anchor='w', pady=(12, 0))

        ttk.Label(settings, text='Connect to your API', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        ttk.Label(settings, text='Use the credentials of an already registered scanner device.',
                  style='Muted.TLabel').pack(anchor='w', pady=(6, 20))
        self.settings_inputs = []
        for title, variable, masked in [('API base URL', self.api, False),
                                         ('Device ID', self.device_id, False),
                                         ('Device secret', self.secret, True)]:
            ttk.Label(settings, text=title).pack(anchor='w', pady=(12, 6))
            entry = ttk.Entry(settings, textvariable=variable, show='*' if masked else '')
            entry.pack(fill='x')
            self.settings_inputs.append(entry)
        ttk.Label(settings, text='64 hexadecimal characters. The secret stays hidden in this window.',
                  style='Muted.TLabel').pack(anchor='w', pady=(6, 18))
        self.save_button = ttk.Button(settings, text='Save settings', style='Primary.TButton', command=self.save_settings)
        self.save_button.pack(anchor='w')
        ttk.Label(settings, text='Settings are stored locally for your Windows account, including the device secret.\n'
                  'Disconnect before editing. No credentials are bundled into the executable.',
                  style='Muted.TLabel', wraplength=720).pack(anchor='w', pady=(22, 8))
        ttk.Label(settings, text=str(self.config_path), style='Muted.TLabel', wraplength=720).pack(anchor='w')

    def _load_settings(self):
        try:
            # Import the existing CLI configuration on first launch, without copying it until Save.
            saved = load_config(self.config_path if self.config_path.exists() else DEFAULT_CONFIG)
            self.api.set(os.getenv('RFID_API_BASE_URL') or saved.get('api_base_url', DEFAULT_API))
            self.device_id.set(os.getenv('RFID_DEVICE_ID') or saved.get('device_id', 'scanner-1'))
            self.secret.set(os.getenv('RFID_DEVICE_SECRET_HEX') or saved.get('device_secret_hex', ''))
        except (ValueError, OSError):
            self.record('ERROR', 'Could not load settings. Enter your API credentials in API settings.')

    def settings(self):
        return validate_settings({'api_base_url': self.api.get().strip().rstrip('/'),
                                  'device_id': self.device_id.get().strip(),
                                  'device_secret_hex': self.secret.get().strip()})

    def save_settings(self):
        try:
            settings = self.settings()
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            save_config(self.config_path, settings)
        except (ValueError, OSError) as error:
            messagebox.showerror('Settings not saved', str(error), parent=self.root)
            return
        self.record('SETTINGS', 'API settings saved locally.')
        messagebox.showinfo('Settings saved', 'Your scanner is ready to connect.', parent=self.root)

    def refresh_ports(self):
        try:
            from serial.tools import list_ports
            ports = sorted(list_ports.comports(), key=lambda port: port.device)
        except ImportError:
            self.record('ERROR', 'Install PySerial from requirements-bridge.txt to connect a scanner.')
            return
        except OSError:
            self.record('ERROR', 'Could not list USB ports. Check the USB connection and refresh.')
            return
        self.port_map = {f'{port.device} — {port.description}': port.device for port in ports}
        self.ports['values'] = list(self.port_map)
        if self.port.get() not in self.port_map:
            self.port.set(next(iter(self.port_map)) if len(ports) == 1 else '')
        if not ports:
            self.hint.set('No USB ports found. Connect the ESP32 with a data USB cable, then select Refresh.')

    def toggle_connection(self):
        if self.worker is not None:
            self.stop.set()
            self.status.set('Disconnecting…')
            self.connect_button.configure(state='disabled')
            return
        try:
            settings = self.settings()
        except ValueError as error:
            self.tabs.select(self.settings_tab)
            messagebox.showerror('Check API settings', str(error), parent=self.root)
            return
        port = self.port_map.get(self.port.get())
        if not port:
            messagebox.showinfo('Choose your scanner', 'Select the ESP32 port. Use Refresh after connecting USB.', parent=self.root)
            return
        self.stop.clear()
        self.status.set('Connecting…')
        self._lock(True)
        self.connect_button.configure(state='disabled')
        self.worker = threading.Thread(target=bridge_worker, args=(port, settings, self.stop, self.events), daemon=True)
        self.worker.start()

    def _lock(self, active):
        self.ports.configure(state='disabled' if active else 'readonly')
        for widget in [self.refresh_button, self.save_button] + self.settings_inputs:
            widget.configure(state='disabled' if active else 'normal')

    def record(self, label, text):
        text = ' '.join(str(text).split())
        self.history.insert('', 0, values=(time.strftime('%H:%M:%S'), label, text), tags=(label,))
        rows = self.history.get_children()
        for row in rows[300:]:
            self.history.delete(row)

    def _stage(self, mode, stage):
        self.mode.set('RETURN' if mode == 'return' else 'RECEIVE')
        stages = {'idle': (0, 'Ready to scan', 'Press Scan on the station to begin. Menu changes the mode.'),
                  'scan_student': (1, 'Tap the student ID', 'Hold the student card near the RFID reader.'),
                  'scan_item': (2, 'Tap the item tag', 'Student ID captured. Hold a different item tag near the reader.'),
                  'confirm': (3, 'Ready to save', 'Both IDs captured. Press Scan to save, or Menu to cancel.')}
        index, title, hint = stages.get(stage, (0, 'Scanner connected', 'Follow the instructions on the station LCD.'))
        self.headline.set(title)
        self.hint.set(hint)
        for number, label in enumerate(self.steps):
            label.configure(bg=self.BLUE if number == index else '#eef2f7',
                            fg='white' if number == index else self.MUTED)

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == 'connected':
                    self.connected = True
                    self.status.set('USB connected')
                    self.badge.configure(bg='#dcfce7', fg='#15803d')
                    self.connect_button.configure(text='Disconnect', state='normal')
                    if self.stop.is_set():
                        self.status.set('Disconnecting…')
                        self.connect_button.configure(state='disabled')
                    self._stage('borrow', 'unknown')
                    self.record('CONNECTED', f'ESP32 on {event[1]}. Waiting for scanner activity.')
                elif event[0] == 'disconnected':
                    # The worker posts this as its last action; no GUI thread touches serial.
                    self.worker = None
                    self.connected = False
                    self._lock(False)
                    self.status.set('Disconnected')
                    self.badge.configure(bg='#e2e8f0', fg=self.MUTED)
                    self.connect_button.configure(text='Connect', state='normal')
                    self.headline.set('Scanner disconnected')
                    self.hint.set('Connect the ESP32 to continue. Recent activity stays here until you close the app.')
                    for label in self.steps:
                        label.configure(bg='#eef2f7', fg=self.MUTED)
                    self.record('DISCONNECTED', 'USB connection closed.')
                elif event[0] == 'stage':
                    self._stage(event[1], event[2])
                elif event[0] == 'message':
                    label, text = event[1:]
                    self.record(label, text)
                    if label in ('SAVED', 'FAILED', 'UNCONFIRMED', 'ERROR'):
                        self.headline.set({'SAVED': 'Transaction saved', 'FAILED': 'Transaction rejected',
                                           'UNCONFIRMED': 'Save not confirmed', 'ERROR': 'Connection needs attention'}[label])
                        self.hint.set(text)
                    if label == 'SAVED':
                        self.saved_count += 1
                        self.count.set(f'{self.saved_count} confirmed saves this session')
        except queue.Empty:
            pass
        if self.closing and self.worker is None:
            self.root.destroy()
            return
        self.root.after(100, self._poll)

    def close(self):
        self.closing = True
        if self.worker is not None:
            self.stop.set()
            self.status.set('Finishing current request…')
            self.connect_button.configure(state='disabled')
            self.hint.set('Waiting for the current API request and scanner acknowledgement before closing.')
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    StationApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
