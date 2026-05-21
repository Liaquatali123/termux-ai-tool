# project_manager.py — Project listing, type detection, loading

from pathlib import Path
from storage_manager import PROJECTS
from github_sync import list_projects, detect_type

def show_list():
    projects = list_projects()
    print(f"📁 Projects ({PROJECTS}/):")
    if not projects:
        print("  (empty — clone a repo: termux-ai clone <url>)")
        return
    for p in projects:
        if "remote" in p and p["remote"]:
            print(f"  📂 {p['name']:25s} [{p['type']}]  → {p['remote']}")
        else:
            print(f"  📂 {p['name']:25s} [{p['type']}]  (local)")

def get_count():
    return len(list(PROJECTS.iterdir())) if PROJECTS.exists() else 0
