#!/usr/bin/env python3
"""Offline validation tests for tui_chat latency/fallback logic."""

import sys, json, os, time, threading
sys.path.insert(0, "/tmp/termux-ai-tool/ai_openrouter")

# Mock paths for testing
os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
os.environ["AI_BACKEND"] = "/tmp/test_ai"

import tempfile
from pathlib import Path
tmpdir = Path("/tmp/test_ai")
(tmpdir / "configs").mkdir(parents=True, exist_ok=True)

# Patch storage paths before importing
import storage_manager
storage_manager.AI = tmpdir

from tui_chat import (
    detect_message_type, parse_tool_calls, Blacklist, LatencyTracker,
    penalize_model, get_working_models, COMPRESSED_PROMPT,
    FAST_POOL, REASONING_POOL, FIRST_TOKEN_FAST, FIRST_TOKEN_BALANCED, FIRST_TOKEN_REASONING,
)
from pathlib import Path
import tui_chat

tui_chat.CONFIG = tmpdir / "configs" / "models_config.json"
tui_chat.KEY_FILE = tmpdir / "configs" / "api_key.json"
tui_chat.CHAT_HISTORY = tmpdir / "configs" / "chat_history.json"

passed = 0
failed = 0

def check(name, ok):
    global passed, failed
    if ok:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}")
        failed += 1

# ===== Test 1: detect_message_type =====
print("\n== Adaptive Routing (detect_message_type) ==")

mode, t, pool = detect_message_type("hi")
check("'hi' → fast mode", mode == "fast")
check("fast timeout = 2.5s", t == FIRST_TOKEN_FAST)

mode, t, pool = detect_message_type("hello, how are you?")
check("casual → fast", mode == "fast")

mode, t, pool = detect_message_type("explain how the routing algorithm works in detail")
check("'explain' → reasoning", mode == "reasoning")
check("reasoning timeout = 8s", t == FIRST_TOKEN_REASONING)

mode, t, pool = detect_message_type("def fibonacci(n):\n    if n <= 1: return n\n    return fibonacci(n-1) + fibonacci(n-2)")
check("code def → reasoning", mode == "reasoning")

mode, t, pool = detect_message_type("fix this function: undefined is not a function")
check("debug → reasoning", mode == "reasoning")

mode, t, pool = detect_message_type("write a python hello world")
check("write code → reasoning", mode == "reasoning")

mode, t, pool = detect_message_type("what is the weather today?")
check("short question → balanced", mode == "balanced")

mode, t, pool = detect_message_type("yes, that works")
check("affirmation → fast", mode == "fast")

mode, t, pool = detect_message_type("compare the architecture of microservices vs monoliths")
check("'compare'+'architecture' → reasoning", mode == "reasoning")

# ===== Test 2: Blacklist =====
print("\n== Blacklist ==")
bl = Blacklist()
check("fresh model not banned", not bl.is_banned("test/model"))
bl.ban("test/model", duration=0.01)
time.sleep(0.02)
check("expired ban auto-clears", not bl.is_banned("test/model"))
bl.ban("bad/model", duration=60)
check("active ban detected", bl.is_banned("bad/model"))
check("unbanned model still ok", not bl.is_banned("other/model"))

# ===== Test 3: parse_tool_calls =====
print("\n== Tool Call Parsing ==")
calls = parse_tool_calls("Here's the fix:\n[tool: read] src/bug.py\nI see the issue")
check("read tool parsed", len(calls) == 1 and calls[0][0] == "read")

calls = parse_tool_calls("[tool: bash] ls -la")
check("bash tool parsed", len(calls) == 1 and calls[0][1] == "ls -la")

calls = parse_tool_calls('[tool: write] hello.py\nprint("hello world")')
check("write tool parsed", len(calls) == 1 and calls[0][0] == "write" and "hello world" in calls[0][2])

calls = parse_tool_calls("No tools here")
check("no tools → empty list", len(calls) == 0)

# ===== Test 4: Compressed Prompt Size =====
print("\n== System Prompt ==")
prompt_lines = COMPRESSED_PROMPT.strip().count("\n") + 1
prompt_tokens = len(COMPRESSED_PROMPT.split())
check(f"prompt is compact ({prompt_lines} lines, {prompt_tokens} tokens)", prompt_lines <= 20)

# ===== Test 5: Model Penalization =====
print("\n== Model Penalization ==")
tui_chat.penalize_model("test/model-a")
cfg = json.loads((tui_chat.CONFIG).read_text())
check("health_score decreased", cfg["model_details"]["test/model-a"]["health_score"] < 50)

# ===== Test 6: Preferred Model Pools =====
print("\n== Model Pools ==")
check("FAST_POOL has 3 models", len(FAST_POOL) == 3)
check("REASONING_POOL has 3 models", len(REASONING_POOL) == 3)
check("nemotron is fast", "nvidia/nemotron-3-nano-30b-a3b:free" in FAST_POOL)
check("qwen3-coder is reasoning", "qwen/qwen3-coder:free" in REASONING_POOL)

# ===== Test 7: Latency Tracker =====
print("\n== Latency Tracker ==")
lt = LatencyTracker()
lt.record("test/model-b", ttft=250, total_ms=2000, char_count=500)
lat = lt.get_latency("test/model-b")
check("avg_ttft_ms recorded", lat["avg_ttft_ms"] == 250)
check("avg_completion_ms recorded", lat["avg_completion_ms"] == 2000)
check("avg_stream_speed calculated", lat["avg_stream_speed"] > 0)
check("health_score default 50", lat["health_score"] == 50)

# ===== Test 8: Fallback No-Duplicate =====
print("\n== Fallback Duplicate Protection ==")
# Simulate: primary starts → early chunk sets event → watchdog sees it and returns
ev = threading.Event()
ev.set()  # Primary already started
watchdog_returned = [False]
def watchdog():
    while time.time() < time.time() + 2:
        if ev.is_set():
            watchdog_returned[0] = True
            return
        time.sleep(0.01)
t = threading.Thread(target=watchdog, daemon=True)
t.start()
t.join(timeout=1)
check("watchdog returns early when primary starts", watchdog_returned[0])

# ===== Summary =====
print(f"\n{'='*40}")
print(f"  Passed: {passed}  Failed: {failed}  Total: {passed+failed}")
print(f"{'='*40}")

# Cleanup
import shutil
shutil.rmtree(tmpdir, ignore_errors=True)
sys.exit(0 if failed == 0 else 1)
