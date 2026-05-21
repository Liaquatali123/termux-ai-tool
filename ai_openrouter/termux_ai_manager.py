#!/usr/bin/env python3
"""termux_ai_manager.py — Unified Termux AI Tool (Python)

Usage:
  python3 termux_ai_manager.py <command>

Commands:
  start           Start AI backend (fast check, no package installs)
  stop            Stop background scanner daemon
  restart         Graceful scanner restart
  doctor          Run full diagnostics
  doctor --repair Full repair + install dependencies
  update          Full system update (repair + deps + files)
  scan            Run model scanner once
  models          Show model scores & latency
  status          Show system health
  sync            Git push/pull all projects
  clone <url>     Clone GitHub repo
  key <token>     Set OpenRouter API key
  list            List all projects
  tui             Launch full-screen TUI chat app
  chat -s <name>  Start named session
  resume [id]     Resume last or named session
  sessions        List saved sessions
  delete-session <id>  Delete a session
  help            Show this help
"""

import sys, os, json, time, shutil, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.chdir(Path(__file__).parent)

from storage_manager import DIRS, AI, PROJECTS, ensure_dirs
from auto_repair import verify as fast_verify, repair as full_repair
from runtime_validator import doctor, get_api_key
from daemon_manager import start as daemon_start, stop as daemon_stop
from daemon_manager import restart as daemon_restart
from dependency_manager import install as install_deps

CONFIG = AI / "configs" / "models_config.json"
KEY_FILE = AI / "configs" / "api_key.json"
SCANNER = AI / "live_model_scanner.py"
LOG_FILE = AI / "logs" / "manager.log"
PID_FILE = AI / "cache" / "scanner.pid"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def load_api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key and KEY_FILE.exists():
        try:
            d = json.loads(KEY_FILE.read_text())
            key = d.get("key", "")
        except: pass
    if key:
        os.environ["OPENROUTER_API_KEY"] = key
    return key

# ===== COMMANDS =====
def cmd_start():
    print("\n╔══════════════════════════════════════════════╗")
    print("║     🤖 UNIFIED TERMUX AI TOOL              ║")
    print("╚══════════════════════════════════════════════╝\n")

    log("🔍 Fast system check...")
    fast_verify()

    key = load_api_key()
    if not key:
        log("⚠️  No API key — AI disabled until: termux-ai key <token>")

    result = daemon_start(key)
    if not result and key:
        log("⚠️  Scanner unavailable — retrying in background")

    print(f"📁 Projects: {PROJECTS}/")
    print(f"📁 AI backend: {AI}/")
    log("✅ System ready")

def cmd_stop():
    daemon_stop()

def cmd_restart():
    key = load_api_key()
    daemon_restart(key)

def cmd_doctor():
    if "--repair" in sys.argv:
        log("🔧 Running full repair...")
        full_repair()
    else:
        doctor()

def cmd_update():
    log("🔄 Updating system...")
    full_repair()
    log("✅ System updated")

def cmd_scan():
    if not SCANNER.exists():
        log("❌ Scanner not found — run: termux-ai install")
        sys.exit(1)
    key = load_api_key()
    if not key:
        log("❌ No API key — set: termux-ai key <token>")
        sys.exit(1)
    r = subprocess.run([sys.executable, os.fsdecode(SCANNER), key, "--once"])
    log("✅ Scan complete" if r.returncode == 0 else "⚠️  Scan had errors")

def cmd_models():
    if CONFIG.exists():
        try:
            c = json.loads(CONFIG.read_text())
            print(f"{'Model':<55} {'Latency':>8} {'Health':>7} {'Category':<12}")
            print("-" * 82)
            for m in c.get("working_models", []):
                d = c.get("model_details", {}).get(m, {})
                lat = d.get("avg_latency", "-")
                h = d.get("health_score", 0)
                cat = d.get("category", "general")
                lat_s = f"{lat}ms" if isinstance(lat, int) else str(lat)
                print(f"{m:<55} {lat_s:>8} {h:>7} {cat:<12}")
        except: print("⚠️  Config corrupted")
    else:
        print("⏳ Run: termux-ai scan")

def cmd_status():
    key = load_api_key()
    print("╔══════════════════════════════════════════════╗")
    print("║           SYSTEM STATUS                     ║")
    print("╚══════════════════════════════════════════════╝\n")
    print(f"{'🔑 OpenRouter:':20s} {'✅ Connected' if key else '❌ No key'} ({key[:12]+'...' if key else ''})")
    from daemon_manager import is_running, get_pid
    pid = get_pid()
    print(f"{'🔄 Scanner:':20s} {'✅ Running (PID ' + pid + ')' if pid and is_running() else '⏳ Not running'}")
    if CONFIG.exists():
        try:
            c = json.loads(CONFIG.read_text())
            w = c.get("working_count", 0)
            r = c.get("rate_limited_count", 0)
            d = c.get("dead_count", 0)
            a = c.get("working_models", ["-"])[0]
            fast = c.get("fastest_model", "-")
            fm = c.get("fastest_ms", "-")
            last = c.get("last_updated", "never")[:19]
            cd = len([m for m in c.get("model_details", {}).values() if m.get("cooldown_until") and m["cooldown_until"]])
            print(f"{'🧠 Active:':20s} {a}")
            print(f"{'📊 Working:':20s} {w}   ⏳ Rate-limited: {r}   ❌ Dead: {d}   🧊 Cooldown: {cd}")
            print(f"{'⚡ Fastest:':20s} {fast} ({fm}ms)")
            print(f"{'🕐 Last scan:':20s} {last}")
        except: print("⏳ Model data unavailable")
    print(f"\n📁 AI:     {AI}/ {'✅' if AI.exists() else '❌'}")
    print(f"📁 Projects: {PROJECTS}/ {'✅' if PROJECTS.exists() else '❌'}")
    pc = len(list(PROJECTS.iterdir())) if PROJECTS.exists() else 0
    print(f"📂 Projects: {pc}")

def cmd_sync():
    from github_sync import sync
    sync()

def cmd_clone(url):
    from github_sync import clone
    clone(url)

def cmd_key(token):
    KEY_FILE.write_text(json.dumps({"key": token, "saved": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2))
    os.environ["OPENROUTER_API_KEY"] = token
    log("✅ API key saved")

def cmd_tui():
    from tui_chat import launch_tui
    key = load_api_key()
    if not key:
        log("⚠️  No API key — AI disabled. Use: termux-ai key <token>")
        return
    launch_tui()

def cmd_list():
    from project_manager import show_list
    show_list()

def cmd_chat():
    from tui_chat import launch_tui, sessions
    key = load_api_key()
    if not key:
        log("⚠️  No API key — AI disabled. Use: termux-ai key <token>")
        return
    if "-s" in sys.argv:
        idx = sys.argv.index("-s")
        if len(sys.argv) > idx + 1:
            name = sys.argv[idx + 1]
            if sessions.exists(name):
                launch_tui(session_id=name)
            else:
                sid = sessions.create(name=name)
                launch_tui(session_id=sid)
        else:
            log("⚠️ Usage: termux-ai chat -s <name>")
    else:
        launch_tui()

def cmd_resume():
    from tui_chat import launch_tui, sessions
    key = load_api_key()
    if not key:
        log("⚠️  No API key — AI disabled. Use: termux-ai key <token>")
        return
    if len(sys.argv) > 2:
        sid = sys.argv[2]
        if sessions.exists(sid):
            launch_tui(session_id=sid)
        else:
            log(f"❌ Session not found: {sid}")
    else:
        last = sessions.get_last()
        if last:
            launch_tui(session_id=last)
        else:
            log("⚠️ No last session — starting fresh")
            launch_tui()

def cmd_sessions():
    from tui_chat import sessions
    lst = sessions.list_sessions()
    if not lst:
        log("📋 No saved sessions")
        return
    print(f"{'ID':<24} {'Name':<20} {'Msgs':>5} {'Model':<30} {'Updated':<20}")
    print("-" * 99)
    for s in lst:
        name = s.get("name", "")[:18]
        mid = s["model"].split("/")[-1][:28] if s.get("model") else ""
        print(f"{s['id']:<24} {name:<20} {s['message_count']:>5} {mid:<30} {s['updated'][:19]:<20}")

def cmd_delete_session():
    if len(sys.argv) < 3:
        log("❌ Usage: termux-ai delete-session <id>")
        return
    from tui_chat import sessions
    sid = sys.argv[2]
    if sessions.exists(sid):
        sessions.delete(sid)
        log(f"🗑️ Deleted: {sid}")
    else:
        log(f"❌ Session not found: {sid}")

def cmd_help():
    print(__doc__)

# ===== MAIN =====
def main():
    ensure_dirs()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    cmds = {
        "start": cmd_start, "stop": cmd_stop, "restart": cmd_restart,
        "doctor": cmd_doctor, "scan": cmd_scan, "models": cmd_models,
        "status": cmd_status, "sync": cmd_sync, "list": cmd_list,
        "tui": cmd_tui, "chat": cmd_chat, "resume": cmd_resume,
        "sessions": cmd_sessions, "delete-session": cmd_delete_session,
        "update": cmd_update, "help": cmd_help,
    }

    if cmd == "clone":
        if len(sys.argv) < 3:
            print("❌ Usage: termux-ai clone <git-url>")
            sys.exit(1)
        cmd_clone(sys.argv[2])
    elif cmd == "key":
        if len(sys.argv) < 3:
            print("❌ Usage: termux-ai key <token>")
            sys.exit(1)
        cmd_key(sys.argv[2])
    elif cmd in cmds:
        cmds[cmd]()
    else:
        print(f"❌ Unknown command: {cmd}\n")
        cmd_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
