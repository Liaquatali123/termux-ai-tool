#!/usr/bin/env python3
"""tui_chat.py — Full-screen Terminal AI Chat (curses TUI)."""

import sys, json, os, time, threading, queue, urllib.request, urllib.error, re, subprocess, select, math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from storage_manager import AI

API_BASE = "https://openrouter.ai/api/v1/chat/completions"
CONFIG = AI / "configs" / "models_config.json"
KEY_FILE = AI / "configs" / "api_key.json"
CHAT_HISTORY = AI / "configs" / "chat_history.json"
PROJECTS = AI.parent / "Projects"
CWD = Path.cwd()

# Timeouts — set dynamically per request (see detect_message_type)
FIRST_TOKEN_FAST = 2.5
FIRST_TOKEN_BALANCED = 5.0
FIRST_TOKEN_REASONING = 8.0
STREAM_HANG_TIMEOUT = 5.0
BLACKLIST_DURATION = 20 * 60  # 20 minutes

FAST_POOL = [
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
    "minimax/minimax-m2.5:free",
]
REASONING_POOL = [
    "qwen/qwen3-coder:free",
    "deepseek/deepseek-chat:free",
    "google/gemini-2.0-flash-exp:free",
]
PREFERRED_MODELS = FAST_POOL + REASONING_POOL + ["openrouter/free"]

COMPRESSED_PROMPT = (
    "You are a terminal-native AI coding assistant (Termux/Android).\n"
    "You act like OpenCode — a developer pair, not a general chatbot.\n\n"
    "Rules:"
    "\n- Concise, code-first, no padding ('Here's how', 'One approach')"
    "\n- Use ```language blocks for code, $ for shell commands"
    "\n- Show file paths in diffs when editing"
    "\n- Prefer doing over explaining: read files, run commands, fix things"
    "\n\nTools available:"
    "\n- [tool: read] path  -  [tool: bash] cmd  -  [tool: write] path\\ncontent"
    "\n- [tool: grep] pattern [path]  -  [tool: glob] pattern"
    f"\n\nProject: {PROJECTS}  Backend: {AI}  CWD: {CWD}"
)

def load_api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key and KEY_FILE.exists():
        try:
            d = json.loads(KEY_FILE.read_text())
            key = d.get("key", "")
        except: pass
    if key:
        os.environ["OPENROUTER_API_KEY"] = key
    return key

# Rolling latency tracker
class LatencyTracker:
    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        try:
            cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
            self._cache = cfg.get("model_details", {})
        except: self._cache = {}

    def _save(self):
        try:
            cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
            cfg["model_details"] = self._cache
            CONFIG.write_text(json.dumps(cfg, indent=2))
        except: pass

    def record(self, model, ttft=None, total_ms=None, char_count=None):
        if "/" not in model: return
        with self._lock:
            d = self._cache.setdefault(model, {})
            if ttft is not None:
                prev = d.get("avg_ttft_ms", 0)
                cnt = d.get("_samples", 0)
                d["avg_ttft_ms"] = int((prev * cnt + ttft) / (cnt + 1))
                d["_samples"] = cnt + 1
            if total_ms is not None:
                prev = d.get("avg_completion_ms", 0)
                cnt = d.get("_samples", 0)
                d["avg_completion_ms"] = int((prev * cnt + total_ms) / (cnt + 1))
            if char_count is not None and total_ms and total_ms > 0:
                speed = char_count / (total_ms / 1000)
                prev = d.get("avg_stream_speed", 0)
                cnt = d.get("_samples", 0)
                d["avg_stream_speed"] = round((prev * cnt + speed) / (cnt + 1), 1)
            self._save()

    def get_latency(self, model):
        d = self._cache.get(model, {})
        return {
            "avg_ttft_ms": d.get("avg_ttft_ms"),
            "avg_completion_ms": d.get("avg_completion_ms"),
            "avg_stream_speed": d.get("avg_stream_speed"),
            "health_score": d.get("health_score", 50),
            "stall_count": d.get("stall_count", 0),
        }

latency_tracker = LatencyTracker()

# Blacklist
class Blacklist:
    def __init__(self):
        self._entries = {}  # model → unban_time
        self._lock = threading.Lock()

    def ban(self, model, duration=None):
        if "/" not in model: return
        with self._lock:
            d = duration or BLACKLIST_DURATION
            self._entries[model] = time.time() + d

    def is_banned(self, model):
        with self._lock:
            expiry = self._entries.get(model)
            if not expiry: return False
            if time.time() > expiry:
                del self._entries[model]
                return False
            return True

    def clean(self):
        with self._lock:
            now = time.time()
            self._entries = {m: e for m, e in self._entries.items() if e > now}

    def list(self):
        self.clean()
        return list(self._entries.keys())

blacklist = Blacklist()

def detect_message_type(text):
    text_lower = text.lower()
    reasoning_kw = ["explain", "how does", "why", "architecture", "design", "compare",
                     "analyze", "debug", "refactor", "optimize", "complex", "architecture",
                     "diagram", "flow", "algorithm", "pattern"]
    fast_kw = ["hi", "hello", "hey", "yes", "no", "ok", "thanks", "summarize",
               "short", "quick", "simple", "what is", "who", "when"]
    score = 0
    for kw in reasoning_kw:
        if kw in text_lower: score += 1
    for kw in fast_kw:
        if kw in text_lower: score -= 1
    if len(text) < 20: score -= 1
    if len(text) > 200: score += 1
    if "```" in text or "def " in text or "function" in text or "class " in text:
        score += 2
    if score >= 2: return "reasoning", FIRST_TOKEN_REASONING, REASONING_POOL
    if score <= -1: return "fast", FIRST_TOKEN_FAST, FAST_POOL
    return "balanced", FIRST_TOKEN_BALANCED, PREFERRED_MODELS

def penalize_model(model):
    if "/" not in model: return
    try:
        cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
        d = cfg.setdefault("model_details", {})
        e = d.setdefault(model, {})
        e["health_score"] = max(0, e.get("health_score", 50) - 5)
        e["last_stall"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        e["stall_count"] = e.get("stall_count", 0) + 1
        if e["stall_count"] >= 3:
            blacklist.ban(model)
        CONFIG.write_text(json.dumps(cfg, indent=2))
    except: pass

def get_working_models():
    try:
        cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
        models = cfg.get("working_models", cfg.get("fallback_order", []))
        details = cfg.get("model_details", {})
        def sort_key(m):
            health = details.get(m, {}).get("health_score", 50)
            pref = PREFERRED_MODELS.index(m) if m in PREFERRED_MODELS else 99
            banned = 1 if blacklist.is_banned(m) else 0
            return (banned, pref, -health)
        models = sorted(set(models), key=sort_key)
        models = [m for m in models if not blacklist.is_banned(m)]
        return models or ["openrouter/free"]
    except: return ["openrouter/free"]

def get_active_model():
    m = get_working_models()
    return m[0] if m else "openrouter/free"

def load_chat_history():
    if CHAT_HISTORY.exists():
        try: return json.loads(CHAT_HISTORY.read_text())
        except: pass
    return []

def save_chat_session(session):
    CHAT_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    hist = load_chat_history()
    hist = [h for h in hist if h.get("id") != session.get("id")]
    hist.append(session)
    CHAT_HISTORY.write_text(json.dumps(hist[-20:], indent=2))

# ---- Tools ----

def tool_read(path):
    target = Path(path)
    if not target.is_absolute(): target = PROJECTS / target
    if not target.exists(): return f"File not found: {target}"
    try:
        content = target.read_text()
        return f"─── {target} ({content.count(chr(10))+1} lines) ───\n{content}"
    except Exception as e: return f"Error: {e}"

def tool_bash(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        out, err = r.stdout or "", r.stderr or ""
        res = ""
        if out: res += f"stdout:\n{out[:2000]}"
        if err: res += f"stderr:\n{err[:1000]}"
        return f"exit {r.returncode}\n{(res or '(no output)').strip()}"
    except subprocess.TimeoutExpired: return "Timed out (30s)"
    except Exception as e: return f"Error: {e}"

def tool_write(path, content):
    target = Path(path)
    if not target.is_absolute(): target = PROJECTS / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.strip())
    return f"Written {len(content.strip())}b to {target}"

def tool_grep(pattern, path=None):
    sp = Path(path) if path else PROJECTS
    if not sp.is_absolute(): sp = PROJECTS / sp
    try:
        res = []
        for f in sp.rglob("*"):
            if f.is_file() and f.suffix in (".py", ".js", ".ts", ".sh", ".json", ".md", ".txt", ".html", ".css"):
                try:
                    for i, line in enumerate(f.read_text().split("\n"), 1):
                        if pattern in line:
                            res.append(f"{f.relative_to(PROJECTS)}:{i}:{line.strip()[:120]}")
                            if len(res) >= 30: break
                except: pass
                if len(res) >= 30: break
        return "\n".join(res) if res else "No matches"
    except Exception as e: return f"Error: {e}"

def tool_glob(pattern):
    try:
        m = [str(f.relative_to(PROJECTS)) for f in sorted(PROJECTS.rglob(pattern))[:30]]
        return "\n".join(m) if m else "No files match"
    except Exception as e: return f"Error: {e}"

def parse_tool_calls(text):
    calls = []
    for m in re.finditer(r"\[tool:\s*(\w+)\](.*?)(?=\[/tool\]|$)", text, re.DOTALL):
        name = m.group(1).lower()
        rest = m.group(2).strip()
        if name == "write":
            lines = rest.split("\n", 1)
            calls.append((name, lines[0].strip(), lines[1].strip() if len(lines) > 1 else ""))
        else:
            calls.append((name, rest, ""))
    for m in re.finditer(r"\[tool:\s*(\w+)\]\s*(.+?)(?:\n|$)", text):
        name = m.group(1).lower()
        arg = m.group(2).strip()
        if name != "write" and not any(c[0] == name and c[1] == arg for c in calls):
            if not any(c[0] == name for c in calls):
                calls.append((name, arg, ""))
    seen = set()
    uniq = []
    for c in calls:
        k = (c[0], c[1])
        if k not in seen: seen.add(k); uniq.append(c)
    return uniq

# ---- Curses TUI ----

import curses

class TUIChat:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.api_key = load_api_key()
        self.model = get_active_model()
        self.conversation = []
        self.current_chat_id = f"chat_{int(time.time())}"
        self.streaming = False
        self.stream_buffer = ""
        self.scroll_offset = 0
        self.chat_list = load_chat_history()
        self.mode = "chat"
        self.history_idx = 0
        self.status_msg = ""
        self.status_time = 0
        self.input_buf = ""
        self.input_pos = 0
        self.project_files = self._scan_project()
        self.current_mode = "balanced"
        self.last_ttft = None
        self.last_speed = None

        curses.curs_set(1)
        curses.use_default_colors()
        self._init_colors()
        self.stdscr.keypad(True)
        self.height, self.width = stdscr.getmaxyx()
        self.content_h = self.height - 6

    def _init_colors(self):
        for i, c in [(1, curses.COLOR_CYAN), (2, curses.COLOR_GREEN), (3, curses.COLOR_YELLOW),
                      (4, curses.COLOR_RED), (5, curses.COLOR_MAGENTA), (6, curses.COLOR_BLUE)]:
            curses.init_pair(i, c, -1)
        curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_WHITE)

    def _scan_project(self):
        files = []
        if PROJECTS.exists():
            for f in sorted(PROJECTS.rglob("*"))[:80]:
                if f.is_file() and f.suffix in (".py", ".js", ".ts", ".sh", ".json", ".md", ".txt", ".html", ".css"):
                    try: files.append(str(f.relative_to(PROJECTS)))
                    except: pass
        return files

    # ---- Drawing ----

    def draw_header(self):
        w = self.get_model_count()
        md = self.model.split("/")[-1][:14]
        latency = latency_tracker.get_latency(self.model)
        ttft = latency.get("avg_ttft_ms")
        speed = latency.get("avg_stream_speed")
        mode_tag = {"fast": "⚡Fast", "balanced": "⚖️Bal", "reasoning": "🧠Deep"}
        tag = mode_tag.get(self.current_mode, "⚖️Bal")
        left = f"  {tag} {md}"
        if ttft: left += f" {ttft}ms"
        if speed: left += f" {speed}cps"
        status = "🌐" if self.api_key else "⚠️"
        right = f"{status} {w} models  "
        if blacklist.list(): right += f"⛔{len(blacklist.list())}  "
        line = left + " " * (self.width - len(left) - len(right)) + right
        self.stdscr.attron(curses.color_pair(7) | curses.A_BOLD)
        self.stdscr.addstr(0, 0, line[:self.width])
        self.stdscr.attroff(curses.color_pair(7) | curses.A_BOLD)
        self.stdscr.attron(curses.A_DIM)
        self.stdscr.addstr(1, 0, "─" * self.width)
        self.stdscr.attroff(curses.A_DIM)

    def draw_content(self):
        top, h = 2, self.content_h
        for y in range(h): self.stdscr.addstr(top + y, 0, " " * self.width)
        if self.mode == "history": return self._draw_history(top, h)

        lines = []
        for msg in self.conversation:
            content = msg.get("content", "")
            ts = msg.get("ts", "")
            if isinstance(content, list): continue
            if msg["role"] == "user":
                lines.append((2, f"  You ({ts}):"))
                for l in content.split("\n"): lines.append((-1, f"    {l}"))
            elif msg["role"] == "assistant":
                info = ""
                if msg.get("_ttft"): info += f" ⏱{msg['_ttft']}ms"
                if msg.get("_speed"): info += f" 📡{msg['_speed']}cps"
                lines.append((1, f"  AI ({ts}){info}:"))
                text = self.stream_buffer if (self.streaming and msg.get("_streaming")) else content
                for l in text.split("\n"): lines.append((-1, f"    {l}"))

        if self.streaming:
            st = "  ..."
            if self.status_msg and "stalled" in self.status_msg.lower():
                st = "  ⚠️ switching..."
            if not lines or lines[-1][1] != st: lines.append((3, st))
            else: lines[-1] = (3, st)

        total = len(lines)
        max_scroll = max(0, total - h)
        if self.scroll_offset > max_scroll: self.scroll_offset = max_scroll
        for i, (color, text) in enumerate(lines[self.scroll_offset:self.scroll_offset + h]):
            y = top + i
            try:
                if color > 0:
                    self.stdscr.attron(curses.color_pair(color) | (curses.A_BOLD if color == 2 else curses.A_NORMAL))
                    self.stdscr.addstr(y, 0, text[:self.width])
                    self.stdscr.attroff(curses.color_pair(color) | (curses.A_BOLD if color == 2 else curses.A_NORMAL))
                else: self.stdscr.addstr(y, 0, text[:self.width])
            except: pass
        if max_scroll > 0:
            pct = int((self.scroll_offset / max_scroll) * 100) if max_scroll else 0
            try: self.stdscr.addstr(top + h - 1, max(0, self.width - 12), f" ↑ {pct}%", curses.A_DIM)
            except: pass

    def _draw_history(self, top, h):
        chats = self.chat_list
        if not chats: return self.stdscr.addstr(top, 2, "No saved chats", curses.color_pair(3))
        self.stdscr.addstr(top, 2, "Saved Chats:", curses.A_BOLD)
        for i, c in enumerate(chats[-h+1:]):
            y = top + 1 + i
            if y >= top + h: break
            title = "New Chat"
            if c.get("messages"):
                first = c["messages"][0].get("content", "")
                title = first[:50] if isinstance(first, str) else "New Chat"
            ts = c.get("timestamp", "")[5:19]
            attr = curses.A_REVERSE if i == self.history_idx else curses.A_NORMAL
            try: self.stdscr.addstr(y, 2, f"{'>' if i == self.history_idx else ' '} {title[:self.width-16]}  {ts}", attr)
            except: pass

    def draw_input(self):
        y = self.height - 4
        try: self.stdscr.addstr(y, 0, "─" * self.width, curses.A_DIM)
        except: pass
        inp_y = y + 1
        self.stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
        self.stdscr.addstr(inp_y, 0, "> ")
        self.stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)
        max_w = self.width - 3
        display = self.input_buf[:max_w]
        self.stdscr.attron(curses.color_pair(8))
        self.stdscr.addstr(inp_y, 2, display + " " * (max_w - len(display)))
        self.stdscr.attroff(curses.color_pair(8))
        self.stdscr.move(inp_y, 2 + min(self.input_pos, max_w))

        status_y = self.height - 1
        if self.status_msg and time.time() - self.status_time < 4:
            self.stdscr.attron(curses.color_pair(3))
            self.stdscr.addstr(status_y, 0, f"  {self.status_msg[:self.width-4]}")
            self.stdscr.attroff(curses.color_pair(3))
        else:
            hints = "Ctrl+N:New  Ctrl+L:Clear  Ctrl+H:History  /write  /read  /run  Esc:Exit"
            self.stdscr.attron(curses.A_DIM)
            self.stdscr.addstr(status_y, 0, f"  {hints[:self.width-4]}")
            self.stdscr.attroff(curses.A_DIM)

    def refresh(self):
        self.stdscr.erase()
        self.height, self.width = self.stdscr.getmaxyx()
        self.content_h = self.height - 6
        self.draw_header()
        self.draw_content()
        self.draw_input()
        self.stdscr.noutrefresh()
        curses.doupdate()

    # ---- Messages & Tools ----

    def set_status(self, msg):
        self.status_msg = msg; self.status_time = time.time()

    def add_message(self, role, content, **kw):
        entry = {"role": role, "content": content, "ts": time.strftime("%H:%M"), **kw}
        self.conversation.append(entry)
        self.scroll_offset = max(0, self._total_lines() - self.content_h)
        return entry

    def _total_lines(self):
        count = 0
        for m in self.conversation:
            count += 2
            count += m.get("content", "").count("\n") + 1
        return count

    def _run_tool(self, name, arg, content=""):
        if name == "read": return tool_read(arg)
        if name == "bash": return tool_bash(arg)
        if name == "write": return tool_write(arg, content)
        if name == "grep":
            p = arg.rsplit(" ", 1)
            return tool_grep(p[0], p[1] if len(p) > 1 else None)
        if name == "glob": return tool_glob(arg)
        return f"Unknown tool: {name}"

    def _stream(self, msgs, q, timeout_val):
        models = get_working_models()
        candidates = list(dict.fromkeys(models + PREFERRED_MODELS + ["openrouter/free"]))
        for model in candidates:
            if blacklist.is_banned(model): continue
            payload = json.dumps({
                "model": model, "messages": msgs,
                "stream": True, "max_tokens": 8192, "temperature": 0.7,
            }).encode()
            req = urllib.request.Request(
                API_BASE, data=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/Liaquatali123/termux-ai-tool",
                    "X-Title": "Termux AI",
                }
            )
            try:
                resp = urllib.request.urlopen(req, timeout=timeout_val + 2)
                sock = resp.fp.raw
                if hasattr(sock, "_sock"): sock = sock._sock
                q.put({"type": "model_active", "model": model})
                full = ""
                got_first = False
                last_token_time = time.monotonic()
                start_time = time.monotonic()
                buf = b""
                # Read in chunks, flush immediately
                while True:
                    ready = select.select([sock], [], [], 0.5)
                    now = time.monotonic()
                    if ready[0]:
                        try:
                            chunk = resp.read(4096)
                        except: break
                        if not chunk: break
                        buf += chunk
                        # Process line by line, flush tokens immediately
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            decoded = line.decode().strip()
                            if decoded.startswith("data: "):
                                raw = decoded[6:]
                                if raw == "[DONE]":
                                    elapsed_ms = int((now - start_time) * 1000)
                                    latency_tracker.record(model, total_ms=elapsed_ms, char_count=len(full))
                                    q.put({"type": "done", "content": full, "model": model})
                                    return
                                try:
                                    data = json.loads(raw)
                                    delta = data.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        if not got_first:
                                            got_first = True
                                            ttft_ms = int((now - start_time) * 1000)
                                            latency_tracker.record(model, ttft=ttft_ms)
                                            q.put({"type": "ttft", "ms": ttft_ms})
                                        full += content
                                        last_token_time = now
                                        q.put({"type": "chunk", "content": content})
                                except: pass
                    else:
                        elapsed = now - start_time
                        if not got_first:
                            if elapsed > timeout_val:
                                penalize_model(model)
                                blacklist.ban(model) if latency_tracker.get_latency(model).get("stall_count", 0) >= 2 else None
                                q.put({"type": "stall", "model": model, "reason": "no_first_token"})
                                break
                        else:
                            if now - last_token_time > STREAM_HANG_TIMEOUT:
                                penalize_model(model)
                                q.put({"type": "stall", "model": model, "reason": "stream_hang"})
                                break
                continue
            except urllib.error.HTTPError as e:
                if e.code in (429, 503, 502):
                    q.put({"type": "stall", "model": model, "reason": f"HTTP {e.code}"})
                    continue
                q.put({"type": "error", "error": f"HTTP {e.code}"})
                return
            except (OSError, urllib.error.URLError):
                q.put({"type": "stall", "model": model, "reason": "connection_error"})
                continue
            except Exception:
                q.put({"type": "stall", "model": model, "reason": "error"})
                continue
        q.put({"type": "error", "error": "All models exhausted"})

    def _stream_with_fallback(self, msgs, q, timeout_val):
        """Launch primary stream + parallel fallback if timeout approaches."""
        fallback_q = queue.Queue()
        primary_t = threading.Thread(target=self._stream, args=(msgs, q, timeout_val), daemon=True)
        primary_t.start()
        # Start a fallback thread that kicks in if primary stalls
        fallback_t = threading.Thread(
            target=self._fallback_watchdog, args=(primary_t, msgs, q, fallback_q, timeout_val), daemon=True
        )
        fallback_t.start()

    def _fallback_watchdog(self, primary_t, msgs, main_q, fb_q, timeout_val):
        """If primary doesn't produce first token in time, launch fallback model."""
        deadline = time.time() + max(1.5, timeout_val - 1)
        got_chunk = False
        while time.time() < deadline:
            if not primary_t.is_alive():
                return  # primary finished
            time.sleep(0.1)
        # Check if primary produced anything
        # We can't easily peek into main_q, so check if streaming status changed
        if got_chunk:
            return
        # Launch fallback with openrouter/free in parallel
        fallback_msgs = [{"role": "system", "content": COMPRESSED_PROMPT}]
        for m in msgs:
            if m.get("role") == "system": continue
            fallback_msgs.append(m)
        t = threading.Thread(
            target=self._stream, args=(fallback_msgs, main_q, timeout_val), daemon=True
        )
        t.start()

    def _agent_loop(self, initial_msgs, timeout_val, mode):
        max_turns = 5
        msgs = list(initial_msgs)
        for turn in range(max_turns):
            full = ""
            self.streaming = True
            self.stream_buffer = ""
            stalled_models = []
            q = queue.Queue()
            self._stream_with_fallback(msgs, q, timeout_val)
            last_chunk_time = time.monotonic()
            ttft_ms = None
            start_time = time.monotonic()

            while True:
                try:
                    ev = q.get(timeout=0.05)
                    if ev["type"] == "chunk":
                        full += ev["content"]
                        self.stream_buffer = full
                        last_chunk_time = time.monotonic()
                    elif ev["type"] == "ttft":
                        ttft_ms = ev["ms"]
                        self.last_ttft = ttft_ms
                    elif ev["type"] == "done":
                        full = ev.get("content", full)
                        self.model = ev.get("model", self.model)
                        self.streaming = False
                        elapsed = int((time.monotonic() - start_time) * 1000)
                        speed = round(len(full) / (elapsed / 1000), 1) if elapsed > 0 else 0
                        self.last_speed = speed
                        break
                    elif ev["type"] == "stall":
                        model = ev.get("model", "?")
                        stalled_models.append(model)
                        self.set_status(f"⚠️ {model.split('/')[-1]} stalled — switching...")
                        self.stream_buffer = f"\n  ⚠️ {model.split('/')[-1]} stalled ({ev.get('reason','')}), trying next..."
                        if self.conversation and self.conversation[-1].get("_streaming"):
                            self.conversation[-1]["content"] = self.stream_buffer
                        self.refresh()
                    elif ev["type"] == "error":
                        self.streaming = False
                        self.set_status(f"❌ {ev.get('error','')}")
                        return full
                except queue.Empty:
                    if not self.streaming: break

            if self.conversation and self.conversation[-1].get("_streaming"):
                self.conversation[-1]["content"] = full
                self.conversation[-1]["_streaming"] = False
                self.conversation[-1]["model"] = self.model
                if ttft_ms: self.conversation[-1]["_ttft"] = ttft_ms
                if self.last_speed: self.conversation[-1]["_speed"] = self.last_speed
            self.stream_buffer = ""

            tool_calls = parse_tool_calls(full)
            if not tool_calls: return full

            for name, arg, content in tool_calls:
                self.set_status(f"🛠 {name} {arg[:30]}...")
                self.refresh()
                result = self._run_tool(name, arg, content)
                msgs.append({"role": "assistant", "content": full})
                msgs.append({"role": "system", "content": f"[tool: {name} {arg}]\n{result[:2000]}"})
                if name == "write": self.set_status(f"✅ Created {arg}")
                elif name == "bash":
                    rc = result.split()[2] if result.startswith("exit ") and len(result.split()) > 2 else "0"
                    self.set_status(f"✅ exit {rc}")
            if tool_calls: continue
            return full
        return full

    def send_message(self, text):
        if not text.strip() or self.streaming: return
        if not self.api_key: return self.set_status("❌ No API key")

        self.add_message("user", text.strip())
        self.streaming = True
        ts = time.strftime("%H:%M")
        self.conversation.append({"role": "assistant", "content": "", "ts": ts, "_streaming": True})
        self.scroll_offset = max(0, self._total_lines() - self.content_h)

        mode, timeout_val, pool = detect_message_type(text)
        self.current_mode = mode
        self.set_status(f"⏳ {mode} mode ({int(timeout_val*1000)}ms timeout)...")

        msgs = [{"role": "system", "content": COMPRESSED_PROMPT}]
        for m in self.conversation:
            if m.get("_streaming"): continue
            msgs.append({"role": m["role"], "content": m["content"]})

        def agent_worker():
            result = self._agent_loop(msgs, timeout_val, mode)
            self.streaming = False
            if self.conversation and self.conversation[-1].get("_streaming"):
                self.conversation[-1]["content"] = result
                self.conversation[-1]["_streaming"] = False
            save_chat_session({
                "id": self.current_chat_id,
                "model": self.model,
                "mode": mode,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "messages": [{"role": m["role"], "content": m["content"]} for m in self.conversation if not m.get("_streaming")],
            })
            self.chat_list = load_chat_history()
            l = latency_tracker.get_latency(self.model)
            ttft = l.get("avg_ttft_ms")
            s = l.get("avg_stream_speed")
            info = f"✅ {self.model.split('/')[-1]}"
            if ttft: info += f" ⏱{ttft}ms"
            if s: info += f" 📡{s}cps"
            self.set_status(info)

        threading.Thread(target=agent_worker, daemon=True).start()

    # ---- Navigation ----

    def toggle_history(self):
        self.mode = "history" if self.mode == "chat" else "chat"
        self.history_idx = 0

    def load_chat_from_history(self, idx):
        chats = self.chat_list
        if not chats or idx >= len(chats): return
        c = chats[-(idx+1)]
        self.conversation = []
        for m in c.get("messages", []):
            self.conversation.append({"role": m["role"], "content": m["content"], "ts": c.get("timestamp", "")[11:16]})
        self.current_chat_id = c.get("id", f"chat_{int(time.time())}")
        self.model = c.get("model", self.model)
        self.mode = c.get("mode", "balanced")
        self.mode = "chat"
        self.scroll_offset = max(0, self._total_lines() - self.content_h)
        self.set_status(f"📜 Loaded from {c.get('timestamp','')[:10]}")

    # ---- Commands ----

    def handle_command(self, cmd):
        parts = cmd.split()
        c = parts[0].lower()
        if c == "/exit": raise KeyboardInterrupt
        elif c == "/clear": self.conversation = []; self.stream_buffer = ""; self.scroll_offset = 0; self.set_status("✅ Cleared")
        elif c == "/model": self.set_status(f"🧠 {self.model} ({self.get_model_count()} models)")
        elif c == "/models": ms = get_working_models(); self.set_status(f"📊 {', '.join(m.split('/')[-1][:15] for m in ms[:5])}")
        elif c == "/latency":
            l = latency_tracker.get_latency(self.model)
            banned = blacklist.list()
            self.set_status(f"⏱ {l.get('avg_ttft_ms','?')}ms  📡{l.get('avg_stream_speed','?')}cps  ⛔{len(banned)} banned")
        elif c == "/key":
            if len(parts) > 1:
                self.api_key = parts[1]
                KEY_FILE.write_text(json.dumps({"key": parts[1], "saved": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2))
                self.set_status("✅ API key saved")
            else: self.set_status(f"🔑 {self.api_key[:12]}..." if self.api_key else "⚠️ No key")
        elif c == "/write":
            if len(parts) < 2: return self.set_status("⚠️ /write <path>")
            last = self.conversation[-1]["content"] if self.conversation else ""
            code = ""
            for m in re.finditer(r"```(\w+)?\n(.*?)```", last, re.DOTALL): code = m.group(2).strip()
            if not code: return self.set_status("⚠️ No code block")
            fpath = " ".join(parts[1:])
            target = Path(fpath)
            if not target.is_absolute(): target = PROJECTS / target
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code)
            self.set_status(f"✅ Created {target}")
        elif c == "/read":
            if len(parts) < 2: return self.set_status("⚠️ /read <path>")
            self.set_status(tool_read(" ".join(parts[1:]))[:self.width-10])
        elif c == "/run":
            if len(parts) < 2: return self.set_status("⚠️ /run <command>")
            r = tool_bash(" ".join(parts[1:]))
            self.add_message("system", r[:500])
            rc = r.split()[2] if r.startswith("exit ") and len(r.split()) > 2 else "?"
            self.set_status(f"✅ exit {rc}")
        elif c == "/project": self.set_status(f"📁 {len(self.project_files)} files")
        elif c == "/help": self.set_status("/exit /clear /model /models /latency /key /write /read /run /project")
        else: self.set_status(f"❌ Unknown: {c}")

    def get_model_count(self):
        return len(get_working_models())

    # ---- Main Loop ----

    def run(self):
        while True:
            self.refresh()
            key = self.stdscr.getch()
            if key == 27: break
            elif key == curses.KEY_RESIZE: continue
            elif key in (10, curses.KEY_ENTER):
                if self.mode == "history": self.load_chat_from_history(self.history_idx)
                elif self.input_buf.strip().startswith("/"):
                    self.handle_command(self.input_buf.strip())
                    self.input_buf = ""; self.input_pos = 0
                else:
                    self.send_message(self.input_buf)
                    self.input_buf = ""; self.input_pos = 0
            elif key in (curses.KEY_BACKSPACE, 127):
                if self.input_pos > 0:
                    self.input_buf = self.input_buf[:self.input_pos-1] + self.input_buf[self.input_pos:]
                    self.input_pos -= 1
            elif key == 21: self.input_buf = ""; self.input_pos = 0
            elif key == curses.KEY_LEFT and self.input_pos > 0: self.input_pos -= 1
            elif key == curses.KEY_RIGHT and self.input_pos < len(self.input_buf): self.input_pos += 1
            elif key == curses.KEY_HOME: self.input_pos = 0
            elif key == curses.KEY_END: self.input_pos = len(self.input_buf)
            elif key == curses.KEY_UP:
                if self.mode == "history": self.history_idx = min(self.history_idx + 1, len(self.chat_list) - 1)
                elif self.scroll_offset > 0: self.scroll_offset -= 1
            elif key == curses.KEY_DOWN:
                if self.mode == "history": self.history_idx = max(self.history_idx - 1, 0)
                else:
                    max_s = max(0, self._total_lines() - self.content_h)
                    if self.scroll_offset < max_s: self.scroll_offset += 1
            elif key == curses.KEY_PPAGE: self.scroll_offset = max(0, self.scroll_offset - self.content_h)
            elif key == curses.KEY_NPAGE:
                max_s = max(0, self._total_lines() - self.content_h)
                self.scroll_offset = min(max_s, self.scroll_offset + self.content_h)
            elif key == 12: self.conversation = []; self.stream_buffer = ""; self.scroll_offset = 0; self.set_status("✅ Cleared")
            elif key == 14:
                self.conversation = []; self.current_chat_id = f"chat_{int(time.time())}"
                self.stream_buffer = ""; self.scroll_offset = 0; self.set_status("✅ New chat")
            elif key == 8: self.toggle_history()
            elif key == 3: break
            elif 32 <= key <= 255 and self.mode == "chat":
                char = chr(key)
                self.input_buf = self.input_buf[:self.input_pos] + char + self.input_buf[self.input_pos:]
                self.input_pos += 1

def launch_tui():
    api_key = load_api_key()
    if not api_key: return print("⚠️  No API key — use: termux-ai key <token>")
    try: curses.wrapper(lambda s: TUIChat(s).run())
    except KeyboardInterrupt: pass
    except Exception as e: print(f"\nTUI error: {e}"); import traceback; traceback.print_exc()

if __name__ == "__main__":
    launch_tui()
