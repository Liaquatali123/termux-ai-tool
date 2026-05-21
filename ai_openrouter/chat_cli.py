#!/usr/bin/env python3
"""chat_cli.py — Interactive AI terminal chat using OpenRouter free models."""

import sys, json, os, time, readline
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from storage_manager import AI
from daemon_manager import get_pid, is_running

CHAT_HISTORY = AI / "configs" / "chat_history.json"
CONFIG = AI / "configs" / "models_config.json"
KEY_FILE = AI / "configs" / "api_key.json"
API_BASE = "https://openrouter.ai/api/v1/chat/completions"

# Color helpers
C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "cyan": "\033[36m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "magenta": "\033[35m",
    "blue": "\033[34m",
}

def color(tag, text):
    return f"{C.get(tag, '')}{text}{C['reset']}"

def load_api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key and KEY_FILE.exists():
        try:
            key = json.loads(KEY_FILE.read_text()).get("key", "")
        except: pass
    return key

def get_active_model():
    try:
        cfg = json.loads(CONFIG.read_text())
        models = cfg.get("working_models", [])
        if models:
            return models[0]
        fo = cfg.get("fallback_order", [])
        if fo:
            return fo[0]
    except: pass
    return "openrouter/free"

def get_working_models():
    try:
        cfg = json.loads(CONFIG.read_text())
        return cfg.get("working_models", [])
    except:
        return []

def load_history():
    if CHAT_HISTORY.exists():
        try:
            return json.loads(CHAT_HISTORY.read_text())
        except: pass
    return []

def save_history(session):
    CHAT_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    history = load_history()
    history.append(session)
    # Keep last 10 sessions
    if len(history) > 10:
        history = history[-10:]
    CHAT_HISTORY.write_text(json.dumps(history, indent=2))

def chat_completion(messages, model, api_key, timeout=30):
    """Non-streaming chat completion with auto-fallback."""
    import urllib.request, urllib.error

    working = get_working_models()
    candidates = [model] + [m for m in working if m != model] + ["openrouter/free"]

    for m in candidates:
        payload = json.dumps({
            "model": m,
            "messages": messages,
            "max_tokens": 2048,
            "temperature": 0.7,
        }).encode()

        req = urllib.request.Request(
            API_BASE,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            data = json.loads(resp.read().decode())
            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
            if content:
                return {"success": True, "content": content, "model": m}
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 502):
                continue
            return {"success": False, "error": f"HTTP {e.code}", "model": m}
        except Exception as e:
            continue

    return {"success": False, "error": "All models exhausted", "model": model}

def show_help():
    print(f"""
{color('cyan', 'Commands:')}
  /model       Show active model
  /status      Show system status
  /retry       Retry last message
  /clear       Clear conversation
  /history     Show saved sessions
  /help        Show this menu
  /exit        Quit chat
""")

def show_status(api_key, model):
    pid = get_pid()
    print(f"\n{color('cyan', '🧠 Model:')}       {model}")
    print(f"{color('cyan', '🔑 API Key:')}     {'Set' if api_key else 'Missing'}")
    print(f"{color('cyan', '🔄 Scanner:')}     {'Running (PID ' + pid + ')' if pid else 'Idle'}")
    working = get_working_models()
    print(f"{color('cyan', '📊 Available:')}   {len(working)} models")
    print()

def chat_loop(api_key, start_model):
    model = start_model
    messages = []
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_count = len(load_history())

    # System prompt
    messages.append({
        "role": "system",
        "content": "You are a helpful AI assistant running in Termux terminal. Be concise, clear, and friendly. Use markdown for formatting when helpful."
    })

    print(f"\n  {color('green', '🧠 Active Model:')} {color('bold', model)}")
    print(f"  {color('dim', '⚡ Auto-switch enabled | Type /help for commands')}\n")

    while True:
        try:
            line = input(f"{color('cyan', 'You')} {color('dim', '>')} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{color('yellow', 'Goodbye!')}")
            break

        if not line:
            continue

        # Internal commands
        if line.startswith("/"):
            cmd = line.lower().split()[0]
            if cmd == "/exit":
                print(f"\n{color('yellow', 'Goodbye!')}")
                break
            elif cmd == "/help":
                show_help()
                continue
            elif cmd == "/clear":
                messages = [messages[0]] if messages else []
                # Reset to just system prompt
                messages = [{"role": "system", "content": messages[0]["content"] if messages else "You are a helpful AI assistant."}]
                print(f"{color('green', '✅ Conversation cleared')}")
                continue
            elif cmd == "/model":
                m = get_active_model()
                print(f"\n{color('cyan', '🧠 Active Model:')} {color('bold', m)}\n")
                continue
            elif cmd == "/status":
                show_status(api_key, model)
                continue
            elif cmd == "/retry":
                if len(messages) <= 1:
                    print(f"{color('yellow', 'Nothing to retry')}")
                    continue
                # Remove last assistant response
                if messages[-1]["role"] == "assistant":
                    messages.pop()
                # Also remove the user's last message so we can resend
                if messages[-1]["role"] == "user":
                    last_user = messages.pop()["content"]
                else:
                    print(f"{color('yellow', 'Nothing to retry')}")
                    continue
                print(f"{color('yellow', '↻ Retrying...')}")
                line = last_user
                # Fall through to normal message handling
            elif cmd == "/history":
                hist = load_history()
                if not hist:
                    print(f"{color('yellow', 'No saved sessions')}")
                    continue
                print(f"\n{color('cyan', '📜 Saved Sessions:')}")
                for i, s in enumerate(hist[-5:], 1):
                    sid = s.get("id", "unknown")
                    msgs = len(s.get("messages", []))
                    ts = s.get("timestamp", "")[:19]
                    print(f"  {i}. {ts} — {msgs} messages")
                print()
                continue
            else:
                print(f"{color('red', f'Unknown: {cmd}')}")
                continue

        # Normal message
        messages.append({"role": "user", "content": line})

        # Typing indicator
        print(f"{color('green', 'AI')} {color('dim', '>')} ", end="", flush=True)

        result = chat_completion(messages, model, api_key)

        if result["success"]:
            content = result["content"].strip()
            model = result["model"]
            print(f"{content}\n")
            messages.append({"role": "assistant", "content": content})
        else:
            print(f"{color('red', f'[{result.get(\"error\",\"error\")}]')}\n")
            # Remove the failed user message so they can retry
            if messages and messages[-1]["role"] == "user":
                messages.pop()

        # Auto-save every response
        save_history({
            "id": session_id,
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "messages": messages[1:] if messages else [],
        })

def launch_chat():
    api_key = load_api_key()
    if not api_key:
        print(f"{color('red', '❌ No API key. Set: termux-ai key <token>')}")
        return

    model = get_active_model()
    print(f"\n  {color('bold', '╔══════════════════════════════════════╗')}")
    print(f"  {color('bold', '║')}     {color('cyan', '🤖 AI Terminal Chat')}            {color('bold', '║')}")
    print(f"  {color('bold', '╚══════════════════════════════════════╝')}")

    try:
        chat_loop(api_key, model)
    except KeyboardInterrupt:
        print(f"\n{color('yellow', 'Goodbye!')}")
    except Exception as e:
        print(f"\n{color('red', f'Chat error: {e}')}")

if __name__ == "__main__":
    launch_chat()
