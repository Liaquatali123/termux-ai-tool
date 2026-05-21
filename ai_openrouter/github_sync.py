# github_sync.py — GitHub clone, pull, push, project detection

import subprocess, json, shutil
from pathlib import Path
from storage_manager import PROJECTS

def parse_url(url):
    import re
    m = re.search(r'github\.com[:\/]([\w-]+)\/([\w.-]+?)(?:\.git)?$', url.strip())
    if not m:
        m = re.match(r'^([\w-]+)\/([\w.-]+)$', url.strip())
    if not m:
        return None
    return {"owner": m.group(1), "repo": m.group(2).replace(".git", ""),
            "full": f"{m.group(1)}/{m.group(2).replace('.git','')}"}

def clone(url):
    parsed = parse_url(url)
    if not parsed:
        print("❌ Invalid GitHub URL")
        return False
    dest = PROJECTS / parsed["repo"]
    if dest.exists():
        print(f"❌ Already exists: {dest}")
        return False
    print(f"📦 Cloning {parsed['repo']}...")
    r = subprocess.run(["git", "clone", url, str(dest)], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"✅ Cloned to {dest}/")
        return True
    else:
        print(f"❌ Clone failed: {r.stderr[:200]}")
        return False

def pull(project):
    d = PROJECTS / project if not project.startswith("/") else Path(project)
    if not (d / ".git").exists():
        print(f"❌ Not a git repo: {d}")
        return False
    r = subprocess.run(["git", "pull", "--rebase"], cwd=str(d), capture_output=True, text=True)
    if r.returncode == 0:
        print(f"✅ {d.name} pulled")
        return True
    print(f"⚠️  Pull: {r.stderr[:200]}")
    return False

def push(project, msg=None):
    d = PROJECTS / project if not project.startswith("/") else Path(project)
    if not (d / ".git").exists():
        print(f"❌ Not a git repo: {d}")
        return False
    ts = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = msg or f"Auto-sync {ts}"
    subprocess.run(["git", "add", "-A"], cwd=str(d), capture_output=True)
    r = subprocess.run(["git", "commit", "-m", msg], cwd=str(d), capture_output=True, text=True)
    r2 = subprocess.run(["git", "push"], cwd=str(d), capture_output=True, text=True)
    if r2.returncode == 0:
        print(f"✅ {d.name} pushed")
        return True
    print(f"⏩ {d.name}: {r.stderr[:100] or r2.stderr[:100]}")
    return False

def sync(project=None):
    if project:
        push(project)
        pull(project)
        return
    for d in PROJECTS.iterdir():
        if (d / ".git").exists():
            changes = subprocess.run(["git", "status", "--porcelain"],
                                     cwd=str(d), capture_output=True, text=True).stdout.strip()
            if changes:
                print(f"🔄 {d.name}: {len(changes.split(chr(10)))} change(s)")
                push(d.name)
            else:
                pull(d.name)

def list_projects():
    projects = []
    for d in PROJECTS.iterdir():
        if not d.is_dir():
            continue
        ptype = detect_type(d)
        remote = ""
        branch = ""
        if (d / ".git").exists():
            try:
                r = subprocess.run(["git", "remote", "get-url", "origin"],
                                   cwd=str(d), capture_output=True, text=True)
                remote = r.stdout.strip()
                r2 = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                    cwd=str(d), capture_output=True, text=True)
                branch = r2.stdout.strip()
            except: pass
        projects.append({"name": d.name, "path": str(d), "type": ptype, "remote": remote, "branch": branch})
    return projects

def detect_type(d):
    files = [f.name for f in d.iterdir()]
    if "package.json" in files:
        try:
            pkg = json.loads((d / "package.json").read_text())
            if "react" in str(pkg.get("dependencies", {})): return "React"
        except: pass
        return "Node.js"
    if "requirements.txt" in files: return "Python"
    if "index.html" in files: return "HTML/JS"
    if "Cargo.toml" in files: return "Rust"
    return "Unknown"
