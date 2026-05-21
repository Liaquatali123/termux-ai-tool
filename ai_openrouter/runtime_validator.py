# runtime_validator.py — Diagnostics & health checks

import shutil, os, json
from storage_manager import DIRS, AI, PROJECTS
from dependency_manager import missing as missing_deps

SCANNER = AI / "live_model_scanner.py"
CONFIG = AI / "configs" / "models_config.json"
BACKEND = AI / "autonomous_model_manager.js"
KEY_FILE = AI / "configs" / "api_key.json"
PID_FILE = AI / "cache" / "scanner.pid"

def get_api_key():
    if KEY_FILE.exists():
        try:
            d = json.loads(KEY_FILE.read_text())
            return d.get("key", "")
        except: pass
    return os.environ.get("OPENROUTER_API_KEY", "")

def doctor():
    _ec = 0
    print("\n╔══════════════════════════════════════════════╗")
    print("║           🔍 SYSTEM DIAGNOSTICS             ║")
    print("╚══════════════════════════════════════════════╝\n")

    # Storage
    if DIRS["ai"].parent.exists():
        print("✅ storage   — accessible")
    else:
        print("❌ storage   — run: termux-setup-storage")
        _ec = 1

    # Dependencies
    deps_ok = True
    for cmd in ["python3", "git", "curl", "jq", "nodejs"]:
        found = shutil.which(cmd)
        if found: print(f"✅ {cmd:11s} — {found}")
        else: print(f"❌ {cmd:11s} — not found"); deps_ok = False; _ec = 1
    if deps_ok: print("✅ All dependencies installed")

    # API key
    key = get_api_key()
    if key: print(f"✅ API key   — {key[:12]}...")
    else: print("⚠️  API key   — not set — run: termux-ai key <token>")

    # Scanner
    if SCANNER.exists(): print(f"✅ scanner   — {SCANNER}")
    elif (AI / "free_model_scanner.py").exists(): print("⚠️  scanner   — needs migration (free_model_scanner.py)")
    else: print("❌ scanner   — not found — run: termux-ai install"); _ec = 1

    # Configs
    if DIRS["configs"].exists(): print(f"✅ configs   — {DIRS['configs']}/")
    else: DIRS["configs"].mkdir(parents=True, exist_ok=True); print("🔧 configs   — auto-created")

    if CONFIG.exists():
        try:
            c = json.loads(CONFIG.read_text())
            print(f"   Models: {c.get('working_count',0)} working, {c.get('rate_limited_count',0)} rate-limited")
            print(f"   Fastest: {c.get('fastest_model','-')} ({c.get('fastest_ms','-')}ms)")
        except: print("   (corrupted config)")
    else: print("   (no scan data — run: termux-ai scan)")

    # Logs
    if DIRS["logs"].exists():
        print(f"✅ logs      — {DIRS['logs']}/")
        lf = DIRS["logs"] / "manager.log"
        print(f"   Size: {lf.stat().st_size if lf.exists() else 0} bytes")
    else: DIRS["logs"].mkdir(parents=True, exist_ok=True); print("🔧 logs      — auto-created")

    # Cache
    if DIRS["cache"].exists(): print(f"✅ cache     — {DIRS['cache']}/")
    else: DIRS["cache"].mkdir(parents=True, exist_ok=True); print("🔧 cache     — auto-created")

    # Scanner PID
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        if os.path.exists(f"/proc/{pid}"):
            print(f"   Scanner: running (PID {pid})")
        else:
            print("   Scanner: PID stale (cleaning)")
            PID_FILE.unlink(missing_ok=True)
    else: print("   Scanner: not running")

    # Backend files
    if BACKEND.exists(): print("✅ backend   — core files present")
    else: print("❌ backend   — missing — run: termux-ai install"); _ec = 1

    # Projects
    if PROJECTS.exists():
        count = len(list(PROJECTS.iterdir()))
        print(f"✅ projects  — {count} project(s)")
    else: PROJECTS.mkdir(parents=True, exist_ok=True); print("🔧 projects  — created")

    print()
    if _ec == 0: print("✅ All systems OK")
    else: print(f"⚠️  {_ec} issue(s) — run: termux-ai start (auto-repair)")
    return _ec
