# dependency_manager.py — Auto-check & install system dependencies

import subprocess, shutil, sys, json, os, time
from pathlib import Path
from storage_manager import AI

STATE_FILE = AI / "configs" / "dependency_state.json"
CACHE_TTL = 3600

DEPS = {
    "python3": {"check": ["python3", "--version"], "pkg": "python"},
    "git": {"check": ["git", "--version"], "pkg": "git"},
    "curl": {"check": ["curl", "--version"], "pkg": "curl"},
    "jq": {"check": ["jq", "--version"], "pkg": "jq"},
    "node": {"check": ["node", "--version"], "pkg": "nodejs", "alt": "nodejs"},
}

def _detect_label(cmd):
    """Map internal dep name to human-readable label."""
    labels = {"python3": "Python", "git": "Git", "curl": "curl",
              "jq": "jq", "node": "Node.js"}
    return labels.get(cmd, cmd)

def _check_one(cmd):
    """Check a single dependency via --version. Returns (found, binary_path)."""
    info = DEPS[cmd]
    # Try primary check
    try:
        r = subprocess.run(info["check"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return True, shutil.which(info["check"][0]) or ""
    except: pass
    # Try alt name
    if "alt" in info:
        alt_path = shutil.which(info["alt"])
        if alt_path:
            try:
                r = subprocess.run([info["alt"], "--version"], capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    return True, alt_path
            except: pass
    # Fallback to shutil.which
    path = shutil.which(cmd) or shutil.which(info.get("alt", ""))
    if path:
        return True, path
    return False, ""

def missing():
    """Return list of dependency names that are not installed."""
    deps = []
    for cmd in DEPS:
        found, _ = _check_one(cmd)
        if not found:
            deps.append(cmd)
    return deps

def _load_state():
    try:
        if STATE_FILE.exists():
            d = json.loads(STATE_FILE.read_text())
            if time.time() - d.get("checked", 0) < CACHE_TTL:
                return d.get("installed", [])
    except: pass
    return None

def _save_state(installed):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "installed": installed,
        "checked": time.time(),
    }, indent=2))

def install():
    deps = missing()
    if not deps:
        installed = [c for c in DEPS if _check_one(c)[0]]
        _save_state(installed)
        return True

    pkg_names = list(set(DEPS[d]["pkg"] for d in deps))
    print(f"📦 Installing: {', '.join(pkg_names)}")
    try:
        r = subprocess.run(["pkg", "install", "-y"] + pkg_names,
                          capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            print("✅ Dependencies installed")
            installed = [c for c in DEPS if _check_one(c)[0]]
            _save_state(installed)
            return True
        else:
            print(f"⚠️  Install output: {r.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print("⚠️  Install timed out")
        return False
    except Exception as e:
        print(f"⚠️  Install failed: {e}")
        return False

def check():
    """Non-blocking check, returns list of missing deps."""
    cached = _load_state()
    if cached is not None:
        for cmd in DEPS:
            found, path = _check_one(cmd)
            label = _detect_label(cmd)
            if found:
                print(f"  ✅ {label:12s} — {path}")
            else:
                print(f"  ⚠️  {label:12s} — not found (cached)")
        missing_deps = [c for c in DEPS if c not in cached]
        if missing_deps:
            print(f"  ⚠️  {len(missing_deps)} missing — run: termux-ai doctor")
        return missing_deps

    missing_deps = missing()
    for cmd in DEPS:
        found, path = _check_one(cmd)
        label = _detect_label(cmd)
        if found:
            print(f"  ✅ {label:12s} — {path}")
        else:
            print(f"  ❌ {label:12s} — not found")
    if missing_deps:
        _save_state([c for c in DEPS if _check_one(c)[0]])
    return missing_deps

def check_python_packages():
    required = ["requests"]
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            print(f"📦 Installing Python package: {pkg}")
            subprocess.run([sys.executable, "-m", "pip", "install", pkg], check=True)
