#!/usr/bin/env python3
"""
live_model_scanner.py
Fetches all free models from OpenRouter, tests each, saves working list.
Usage: python3 live_model_scanner.py [api_key]
Outputs JSON to stdout for JS consumption.
"""

import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
MODELS_URL = "https://openrouter.ai/api/v1/models"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

PRIORITY = ["openrouter/free", "qwen/", "deepseek/", "meta-llama/", "google/gemma", "nvidia/", "openai/gpt-oss", "poolside/", "z-ai/"]

def get_key():
    k = os.environ.get("OPENROUTER_API_KEY", "")
    if not k and len(sys.argv) > 1:
        k = sys.argv[1]
    return k

def fetch_models(key):
    req = urllib.request.Request(MODELS_URL)
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        return sorted(set(m["id"] for m in data.get("data", []) if ":free" in m["id"]))
    except Exception as e:
        print(f"  Fetch error: {e}", file=sys.stderr)
        return []

def prioritize(models):
    def sort_key(m):
        for i, p in enumerate(PRIORITY):
            if m.startswith(p):
                return (i, m)
        return (len(PRIORITY), m)
    return sorted(models, key=sort_key)

def test_model(model_id, key):
    payload = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 3, "temperature": 0
    }).encode()
    req = urllib.request.Request(CHAT_URL, data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        ms = int((time.time() - t) * 1000)
        return ("working", ms, "")
    except urllib.error.HTTPError as e:
        ms = int((time.time() - t) * 1000)
        body = e.read().decode()
        try:
            err = json.loads(body)
            code = err.get("error", {}).get("code", e.code)
            msg = err.get("error", {}).get("message", "")[:80]
        except:
            code = e.code
            msg = ""
        if code == 429:
            return ("rate_limited", ms, msg)
        elif code == 404:
            return ("not_found", ms, msg)
        return (f"error_{code}", ms, msg)
    except Exception as e:
        ms = int((time.time() - t) * 1000)
        return ("timeout", ms, str(e)[:60])

def main():
    key = get_key()
    if not key:
        print(json.dumps({"error": "No API key provided", "working": [], "fallback_order": ["openrouter/free"]}))
        sys.exit(1)

    print(f"\n{'='*55}", file=sys.stderr)
    print(f"  LIVE MODEL SCANNER", file=sys.stderr)
    print(f"{'='*55}\n", file=sys.stderr)

    models = prioritize(fetch_models(key))
    print(f"  Found {len(models)} free models\n", file=sys.stderr)

    working = []
    rate_limited = []
    not_found = []
    timeouts = []
    results = []

    for i, m in enumerate(models[:40], 1):
        status, ms, msg = test_model(m, key)
        icon = {"working": "✅", "rate_limited": "⏳", "not_found": "❌", "timeout": "⚡"}.get(status, "❓")
        print(f"  [{i:02d}] {icon} {m:<48} {status:<14} {ms}ms", file=sys.stderr)
        results.append({"model": m, "status": status, "ms": ms, "error": msg})

        if status == "working":
            working.append(m)
        elif status == "rate_limited":
            rate_limited.append(m)
        elif status == "not_found":
            not_found.append(m)
        else:
            timeouts.append(m)

        if status == "rate_limited":
            time.sleep(0.3)

    fallback = working + rate_limited + ["openrouter/free"]

    config = {
        "timestamp": datetime.now().isoformat(),
        "total": len(models),
        "tested": len(results),
        "working": working,
        "rate_limited": rate_limited,
        "not_found": not_found,
        "timeouts": timeouts,
        "fallback_order": fallback,
        "fastest_model": working[0] if working else "openrouter/free",
        "best_ms": min((r["ms"] for r in results if r["status"] == "working"), default=0),
    }

    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\n{'='*55}", file=sys.stderr)
    print(f"  ✅ Working: {len(working)}", file=sys.stderr)
    print(f"  ⏳ Rate-limited: {len(rate_limited)}", file=sys.stderr)
    print(f"  ❌ Not found: {len(not_found)}", file=sys.stderr)
    print(f"  ⚡ Timeouts: {len(timeouts)}", file=sys.stderr)
    print(f"  🏆 Fastest: {config['fastest_model']} ({config['best_ms']}ms)", file=sys.stderr)
    print(f"  📁 Config saved: {CONFIG_FILE}", file=sys.stderr)
    print(f"{'='*55}\n", file=sys.stderr)

    print(json.dumps({"active": config["fastest_model"], "working": working, "fallback": fallback}))

if __name__ == "__main__":
    main()
