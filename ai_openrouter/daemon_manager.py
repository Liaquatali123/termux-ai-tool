# daemon_manager.py — PID management, background scanner watchdog

import os, signal, subprocess, sys, time
from pathlib import Path
from storage_manager import AI

PID_FILE = AI / "cache" / "scanner.pid"
SCANNER = AI / "live_model_scanner.py"
LOG = AI / "logs" / "scanner.log"

def _validate_scanner():
    if not SCANNER.exists():
        return False, "Scanner not found"
    if not SCANNER.name.endswith(".py"):
        return False, f"Invalid scanner type: {SCANNER.name} (must be .py)"
    return True, "ok"

def is_running():
    if not PID_FILE.exists():
        return False
    pid = PID_FILE.read_text().strip()
    if not pid.isdigit():
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ProcessLookupError):
        PID_FILE.unlink(missing_ok=True)
        return False

def start(api_key):
    if is_running():
        pid = PID_FILE.read_text().strip()
        print(f"⏩ Scanner already running (PID {pid})")
        return True

    valid, msg = _validate_scanner()
    if not valid:
        print(f"⚠️  {msg}")
        return False
    if not api_key:
        print("⚠️  No API key — scanner not started")
        return False

    try:
        print("🧠 Launching scanner via python3")
        proc = subprocess.Popen(
            [sys.executable, os.fsdecode(SCANNER), api_key, "--daemon"],
            stdout=open(LOG, "a"), stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        PID_FILE.write_text(str(proc.pid))
        print(f"✅ Scanner started (PID {proc.pid})")
        return True
    except Exception as e:
        print(f"❌ Scanner failed: {e}")
        return False

def stop():
    if not PID_FILE.exists():
        print("⏩ Scanner not running")
        return True
    pid = PID_FILE.read_text().strip()
    try:
        os.kill(int(pid), signal.SIGTERM)
        time.sleep(0.5)
        PID_FILE.unlink(missing_ok=True)
        print("🛑 Scanner stopped")
    except (OSError, ProcessLookupError):
        PID_FILE.unlink(missing_ok=True)
        print("🛑 Scanner PID cleaned")
    return True

def restart(api_key):
    stop()
    time.sleep(0.5)
    return start(api_key)

def get_pid():
    if is_running():
        return PID_FILE.read_text().strip()
    return None
