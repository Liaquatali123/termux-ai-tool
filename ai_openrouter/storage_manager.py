# storage_manager.py — Storage permission & path handling

import os
from pathlib import Path

BASE = Path("/storage/emulated/0")
AI = BASE / "Download/ai_openrouter"
PROJECTS = BASE / "Projects"

DIRS = {
    "ai": AI,
    "projects": PROJECTS,
    "configs": AI / "configs",
    "logs": AI / "logs",
    "cache": AI / "cache",
}

def ensure_dirs():
    for name, path in DIRS.items():
        path.mkdir(parents=True, exist_ok=True)

def check_storage():
    if not BASE.exists():
        os.system("termux-setup-storage 2>/dev/null")
        import time; time.sleep(2)
    return BASE.exists()

def get_path(name):
    return DIRS.get(name)

def all_ok():
    return all(p.exists() for p in DIRS.values())
