#!/usr/bin/env python3
"""install.py — Termux one-line installer for termux-ai-tool"""

import subprocess, sys, shutil, os, time
from pathlib import Path

BIN = Path("/data/data/com.termux/files/usr/bin")
AI = Path("/storage/emulated/0/Download/ai_openrouter")
PROJECTS = Path("/storage/emulated/0/Projects")
HOME = Path.home()
BASHRC = HOME / ".bashrc"

def run(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, **kw)

def info(msg): print(f"ℹ️  {msg}")
def ok(msg):   print(f"✅ {msg}")
def err(msg):  print(f"❌ {msg}")

def main():
    print("\n╔══════════════════════════════════════════════╗")
    print("║   🤖 TERMUX AI TOOL INSTALLER              ║")
    print("╚══════════════════════════════════════════════╝\n")

    # 1. Storage
    info("Requesting storage access...")
    os.system("termux-setup-storage 2>/dev/null")
    time.sleep(1)

    # 2. Dependencies
    info("Installing dependencies...")
    run(["pkg", "update", "-y", "-q"])
    for dep in ["python", "nodejs", "git", "jq", "curl", "openssh"]:
        if shutil.which(dep):
            ok(f"{dep} already installed")
        else:
            info(f"  Installing {dep}...")
            r = run(["pkg", "install", "-y", dep])
            if r.returncode == 0: ok(f"{dep} installed")
            else: err(f"Failed: {dep}")

    # 3. Folders
    info("Creating storage folders...")
    for d in [AI / "configs", AI / "logs", AI / "cache", PROJECTS]:
        d.mkdir(parents=True, exist_ok=True)
    ok(f"Storage: {AI}/")
    ok(f"Projects: {PROJECTS}/")

    # 4. Deploy AI backend (force overwrite all files)
    info("Deploying AI backend...")
    src = Path(__file__).parent / "ai_openrouter"
    if src.exists():
        for f in src.iterdir():
            target = AI / f.name
            if f.is_file():
                shutil.copy2(str(f), str(target))
                # Ensure .py files are readable
                if f.suffix == ".py":
                    target.chmod(0o644)
        for py in AI.glob("*.py"):
            py.chmod(0o644)
        ok("AI backend files deployed")
    else:
        err("ai_openrouter/ not found alongside install.py")

    # 5. Install termux-ai command
    info("Installing 'termux-ai' command...")
    launcher = AI / "termux-ai"
    if launcher.exists():
        shutil.copy2(str(launcher), str(BIN / "termux-ai"))
        (BIN / "termux-ai").chmod(0o755)
        ok(f"termux-ai → {BIN}/termux-ai (Python engine)")
    else:
        err("termux-ai launcher not found")

    # 6. Aliases
    info("Adding aliases to ~/.bashrc...")
    aliases = [
        "alias ai-status='termux-ai status'",
        "alias ai-models='termux-ai models'",
        "alias ai-scan='termux-ai scan'",
        "alias ai-sync='termux-ai sync'",
        "alias ai-serve='termux-ai serve'",
    ]
    bashrc = BASHRC.read_text() if BASHRC.exists() else ""
    for a in aliases:
        if a not in bashrc:
            bashrc += a + "\n"
    BASHRC.write_text(bashrc)
    ok("Aliases added: ai-status, ai-models, ai-scan, ai-sync, ai-serve")

    # Done
    print("\n╔══════════════════════════════════════════════╗")
    print("║   ✅ INSTALLATION COMPLETE                  ║")
    print("╚══════════════════════════════════════════════╝\n")
    print("  1. Set your API key:")
    print("     termux-ai key 'sk-or-v1-...'\n")
    print("  2. Run diagnostics:")
    print("     termux-ai doctor\n")
    print("  3. Scan for models:")
    print("     termux-ai scan\n")
    print("  4. Start the AI backend:")
    print("     termux-ai start\n")
    print("  5. Clone a project:")
    print("     termux-ai clone https://github.com/user/repo.git\n")
    print("  6. Launch AI Chat web app:")
    print("     termux-ai serve\n")
    print("  Reload: source ~/.bashrc\n")

if __name__ == "__main__":
    main()
