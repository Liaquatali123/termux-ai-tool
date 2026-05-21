# dependency_manager.py — Auto-check & install system dependencies

import subprocess, shutil, sys

DEPS = ["python3", "git", "curl", "jq", "nodejs"]

def missing():
    return [d for d in DEPS if not shutil.which(d)]

def install():
    deps = missing()
    if not deps:
        return True
    print(f"📦 Installing: {' '.join(deps)}")
    try:
        subprocess.run(["pkg", "install", "-y"] + deps, check=True, capture_output=True)
        print("✅ Dependencies installed")
        return True
    except subprocess.CalledProcessError:
        print(f"⚠️  Auto-install failed. Run: pkg install {' '.join(deps)}")
        return False

def check_python_packages():
    required = ["requests"]
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            print(f"📦 Installing Python package: {pkg}")
            subprocess.run([sys.executable, "-m", "pip", "install", pkg], check=True)

def all_ok():
    return len(missing()) == 0
