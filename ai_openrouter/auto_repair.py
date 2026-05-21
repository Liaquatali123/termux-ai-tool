# auto_repair.py — Self-healing system with startup/full modes

import shutil, json
from pathlib import Path
from storage_manager import AI, ensure_dirs, check_storage
from dependency_manager import install as install_deps, missing as missing_deps

SCANNER = AI / "live_model_scanner.py"
FREE_SCANNER = AI / "free_model_scanner.py"
CONFIG_FILE = AI / "configs" / "models_config.json"
BACKEND_FILES = [
    "autonomous_model_manager.js", "live_model_scanner.py",
    "smart_retry_system.js", "overload_detector.js", "busy_model_tracker.js",
]

def verify():
    """Fast startup check: paths + key + scanner. No package installs."""
    issues = 0
    ensure_dirs()
    if not check_storage():
        print("⚠️  Storage not accessible — continuing in limited mode")
        issues += 1
    md = missing_deps()
    if md:
        print(f"⚠️  {len(md)} dep(s) missing — run: termux-ai doctor --repair")
    if not SCANNER.exists():
        FREE = AI / "free_model_scanner.py"
        if FREE.exists():
            FREE.rename(SCANNER)
            print("🔄 Migrated free_model_scanner.py → live_model_scanner.py")
        else:
            src = Path(__file__).parent / "live_model_scanner.py"
            if src.exists():
                shutil.copy2(str(src), str(AI))
                print("🔧 Deployed live_model_scanner.py")
            else:
                print("⚠️  Scanner not deployed — continuing without scanner")
                issues += 1
    for f in BACKEND_FILES:
        target = AI / f
        if not target.exists():
            src = Path(__file__).parent / f
            if src.exists():
                shutil.copy2(str(src), str(target))
    if not CONFIG_FILE.exists():
        stub = {"timestamp": "", "working_models": ["openrouter/free"],
                "fallback_order": ["openrouter/free"], "model_details": {},
                "working_count": 0, "rate_limited_count": 0}
        CONFIG_FILE.write_text(json.dumps(stub, indent=2))
        print("🔧 Created stub config")
    return issues

def repair():
    """Full repair: dependencies + everything. Runs on doctor --repair / update."""
    issues = verify()
    print("📦 Checking dependencies...")
    if not install_deps():
        print("⚠️  Some dependencies could not be installed")
        issues += 1
    if issues:
        print(f"⚠️  {issues} issue(s) remaining — run: termux-ai doctor")
    else:
        print("✅ System fully repaired")
    return issues == 0
