# auto_repair.py — Self-healing system, fixes common issues automatically

import shutil, os
from pathlib import Path
from storage_manager import AI, ensure_dirs, check_storage, DIRS
from dependency_manager import install as install_deps

SCANNER = AI / "live_model_scanner.py"
FREE_SCANNER = AI / "free_model_scanner.py"
CONFIG_FILE = AI / "configs" / "models_config.json"
BACKEND_FILES = [
    "autonomous_model_manager.js", "live_model_scanner.py",
    "smart_retry_system.js", "overload_detector.js", "busy_model_tracker.js",
]

def repair():
    issues = 0
    fixes = 0

    # 1. Storage
    if not check_storage():
        print("⚠️  Storage not accessible — continuing anyway")
        issues += 1

    # 2. Dirs
    ensure_dirs()

    # 3. Dependencies
    if not install_deps():
        issues += 1

    # 4. Migrate scanner
    if FREE_SCANNER.exists() and not SCANNER.exists():
        FREE_SCANNER.rename(SCANNER)
        print("🔄 Migrated free_model_scanner.py → live_model_scanner.py")
        fixes += 1

    # 5. Deploy backend files from repo sibling
    if not SCANNER.exists():
        script_dir = Path(__file__).parent
        src = script_dir / "live_model_scanner.py"
        if src.exists():
            shutil.copy2(str(src), str(AI))
            print("🔧 Deployed live_model_scanner.py")
            fixes += 1
        else:
            print("⚠️  Scanner not found — run: termux-ai install")
            issues += 1

    # 6. Core backend files
    for f in BACKEND_FILES:
        target = AI / f
        if not target.exists():
            src = Path(__file__).parent / f
            if src.exists():
                shutil.copy2(str(src), str(target))
                fixes += 1

    # 7. Config file stub
    if not CONFIG_FILE.exists():
        import json
        stub = {"timestamp": "", "working_models": ["openrouter/free"],
                "fallback_order": ["openrouter/free"], "model_details": {},
                "working_count": 0, "rate_limited_count": 0}
        CONFIG_FILE.write_text(json.dumps(stub, indent=2))
        print("🔧 Created stub config")
        fixes += 1

    if issues:
        print(f"⚠️  {issues} issue(s), {fixes} fixed")
    else:
        print(f"✅ All clear ({fixes} auto-fixes applied)")
    return issues == 0
