# bridge.py — reads ESP32 serial, serves live JSON over HTTP
import json
import threading
import time
from collections import deque
from datetime import datetime
from flask import Flask, jsonify
import serial
import serial.tools.list_ports

# ───────── CONFIG ─────────
SERIAL_PORT   = "COM3"     # ← change if needed
BAUD_RATE     = 115200
HTTP_PORT     = 5000
HISTORY_LEN   = 60

# ───────── SHARED STATE ─────────
latest = {
    "distance":  None,
    "alert":     False,
    "buzzer":    False,
    "led_green": False,
    "led_red":   False,
    "timestamp": None,
    "connected": False,
}
history = deque(maxlen=HISTORY_LEN)
lock = threading.Lock()


def serial_reader():
    while True:
        try:
            ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            time.sleep(2)                 # ESP32 resets when serial opens
            ser.reset_input_buffer()
            print(f"[bridge] Connected to {SERIAL_PORT}")

            with lock:
                latest["connected"] = True

            while True:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Ignore the "ready" boot message
                if "status" in data and "distance" not in data:
                    continue

                with lock:
                    latest["distance"]  = data.get("distance")
                    latest["alert"]     = data.get("alert", False)
                    latest["buzzer"]    = data.get("buzzer", False)
                    latest["led_green"] = data.get("led_green", False)
                    latest["led_red"]   = data.get("led_red", False)
                    latest["timestamp"] = datetime.now().isoformat()
                    latest["connected"] = True

                    history.append({
                        "time":     latest["timestamp"],
                        "distance": latest["distance"],
                        "alert":    latest["alert"],
                    })

        except serial.SerialException as e:
            print(f"[bridge] Serial error: {e} — retrying in 3s")
            with lock:
                latest["connected"] = False
            time.sleep(3)


# ───────── HTTP SERVER ─────────
app = Flask(__name__)

@app.route("/data")
def get_data():
    with lock:
        return jsonify({**latest, "history": list(history)})

@app.route("/health")
def health():
    with lock:
        return jsonify({"connected": latest["connected"]})


if __name__ == "__main__":
    print("[bridge] Available ports:",
          [p.device for p in serial.tools.list_ports.comports()])
    threading.Thread(target=serial_reader, daemon=True).start()
    app.run(host="127.0.0.1", port=HTTP_PORT, debug=False, use_reloader=False)