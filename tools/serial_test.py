#!/usr/bin/env python3
"""Plain serial monitor for debugging, no dashboard needed.

    python tools/serial_test.py [port] [baud]

Prints every line from the ESP32 and sends PING each second.
Type F, B, L, R or S + Enter to send CMD,<x>. Ctrl+C to quit.
"""
import sys
import threading
import time

import serial

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

try:
    ser = serial.Serial(port, baud, timeout=0.3)
except Exception as exc:
    sys.exit(f"Cannot open {port}: {exc}")
print(f"Opened {port} @ {baud}. Type F/B/L/R/S + Enter. Ctrl+C quits.")
ser.write(b"HELLO?\n")


def pinger():
    while True:
        try:
            ser.write(b"PING\n")
        except Exception:
            return
        time.sleep(1)


threading.Thread(target=pinger, daemon=True).start()
threading.Thread(target=lambda: [print("<", ser.readline().decode(errors="replace").strip())
                                 for _ in iter(int, 1)], daemon=True).start()
try:
    for line in sys.stdin:
        c = line.strip().upper()
        if c in ("F", "B", "L", "R", "S"):
            ser.write(f"CMD,{c}\n".encode())
            print(">", f"CMD,{c}")
except KeyboardInterrupt:
    ser.write(b"CMD,S\n")
    print("\nStop sent. Bye.")
