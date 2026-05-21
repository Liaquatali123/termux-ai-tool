#!/usr/bin/env python3
"""tui_chat.py — Full-screen Terminal AI Chat (curses TUI)."""

import sys, json, os, time, threading, queue, urllib.request, urllib.error, re, subprocess, select
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from storage_manager import AI

API_BASE = "https://openrouter.ai/api/v1/chat/completions"
CONFIG = AI / "configs" / "models_config.json"
KEY_FILE = AI / "configs" / "api_key.json"
CHAT_HISTORY = AI / "configs" / "chat_history.json"
PROJECTS = AI.parent / "Projects"
CWD = Path.cwd()

FIRST_TOKEN_TIMEOUT = 5
STREAM_HANG_TIMEOUT = 5

PREFERRED_MODELS = [
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
    "minimax/minimax-m2.5:free",
    "openrouter/free",
]

def penalize_model(model):
    if "/" not in model: return
    try:
        cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
        details = cfg.setdefault("model_details", {})
        entry = details.setdefault(model, {})
        entry["health_score"] = max(0, entry.get("health_score", 50) - 5)
        entry["last_stall"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        entry["stall_count"] = entry.get("stall_count", 0) + 1
        cfg["health_pentalized_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        CONFIG.write_text(json.dumps(cfg, indent=2))
    except: pass

def record_latency(model, ttft=None, full_ms=None):
    if "/" not in model: return
    try:
        cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
        details = cfg.setdefault("model_details", {})
        entry = details.setdefault(model, {})
        if ttft is not None:
            entry["avg_first_token_ms"] = int((entry.get("avg_first_token_ms", 0) + ttft) / 2) if entry.get("avg_first_token_ms") else int(ttft)
        if full_ms is not None:
            entry["avg_latency"] = int((entry.get("avg_latency", 0) + full_ms) / 2) if entry.get("avg_latency") else int(full_ms)
        CONFIG.write_text(json.dumps(cfg, indent=2))
    except: pass

TOOL_DESC = """## Tools
You have tools available. To use a tool, include this exact format in your response:
[tool: read] <filepath>
[tool: bash] <command>
[tool: write] <filepath>
<file content here>
[tool: grep] <pattern> [path]
[tool: glob] <pattern>

After using a tool, the system will show you the result. You can use multiple tools.

- `read`: read a file (relative paths under Projects/)
- `bash`: run any shell command
- `write`: create or overwrite a file (content between the tags)
- `grep`: search file contents
- `glob`: find files by name pattern"""

SYSTEM_PROMPT = f"""You are an AI coding assistant running in Termux on Android as part of termux-ai-tool. You act like OpenCode — a terminal-native AI for developers.

## Your identity
- You are a coding expert, not a general chatbot
- You live in a terminal environment (Termux on Android)
- You work with Python, JavaScript, Shell, and common languages
- You are practical and action-oriented
- You solve problems: when given a task, you figure out what files to read, what commands to run, and what to create

## Response style
- **Concise by default**: give the answer directly, add detail only when needed
- **Code-first**: always show code in ```language blocks
- **Commands**: prefix shell commands with `$ ` or use ```bash
- **No padding**: skip "I understand your question" / "Here's how you can..." / "One approach is..."
- **Natural**: talk like a developer pairing with you, not a textbook
- **Show, don't tell**: instead of explaining what you'd do, just read the file and fix it

## Context
- Project root: {PROJECTS}
- AI backend: {AI}
- Current working dir: {CWD}
- You use OpenRouter free models with auto-failover

{TOOL_DESC}"""

# ---- Shared Engine ----

def load_api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key and KEY_FILE.exists():
        try: key = json.loads(KEY_FILE.read_text()).get("key", "")
        except: pass
    return key

def get_working_models():
    try:
        cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
        models = cfg.get("working_models", cfg.get("fallback_order", []))
        details = cfg.get("model_details", {})
        # Sort: preferred first, then by health_score desc, rest at end
        def sort_key(m):
            health = details.get(m, {}).get("health_score", 50)
            pref = PREFERRED_MODELS.index(m) if m in PREFERRED_MODELS else 99
            return (pref, -health)
        models = sorted(set(models), key=sort_key)
        if not models: return ["openrouter/free"]
        return models
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
        lines = content.split("\n")
        return f"─── {target} ({len(lines)} lines) ───\n{content}"
    except Exception as e:
        return f"Error reading {target}: {e}"

def tool_bash(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        out = r.stdout or ""
        err = r.stderr or ""
        result = ""
        if out: result += f"stdout:\n{out[:2000]}"
        if err: result += f"stderr:\n{err[:1000]}"
        if not result: result = "(no output)"
        return f"exit code {r.returncode}\n{result.strip()}"
    except subprocess.TimeoutExpired: return "Command timed out (30s)"
    except Exception as e: return f"Error: {e}"

def tool_write(path, content):
    target = Path(path)
    if not target.is_absolute(): target = PROJECTS / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.strip())
    return f"Written {len(content.strip())} bytes to {target}"

def tool_grep(pattern, path=None):
    search_path = Path(path) if path else PROJECTS
    if not search_path.is_absolute(): search_path = PROJECTS / search_path
    try:
        results = []
        for f in search_path.rglob("*"):
            if f.is_file() and f.suffix in (".py", ".js", ".ts", ".sh", ".json", ".md", ".txt", ".html", ".css"):
                try:
                    for i, line in enumerate(f.read_text().split("\n"), 1):
                        if pattern in line:
                            results.append(f"{f.relative_to(PROJECTS)}:{i}: {line.strip()[:120]}")
                except: pass
                if len(results) >= 30:
                    break
        if not results: return "No matches"
        return "\n".join(results)
    except Exception as e:
        return f"Error: {e}"

def tool_glob(pattern):
    try:
        matches = [str(f.relative_to(PROJECTS)) for f in sorted(PROJECTS.rglob(pattern))[:30]]
        if not matches: return "No files match"
        return "\n".join(matches)
    except Exception as e:
        return f"Error: {e}"

TOOLS = {"read": tool_read, "bash": tool_bash, "grep": tool_grep, "glob": tool_glob}

def parse_tool_calls(text):
    calls = []
    # Match [tool: name] args ... content ... [/tool]
    for m in re.finditer(r"\[tool:\s*(\w+)\](.*?)(?=\[/tool\]|$)", text, re.DOTALL):
        name = m.group(1).lower()
        rest = m.group(2).strip()
        if name == "write":
            lines = rest.split("\n", 1)
            arg = lines[0].strip()
            content = lines[1].strip() if len(lines) > 1 else ""
            calls.append((name, arg, content))
        else:
            calls.append((name, rest.strip(), ""))
    # Also match inline [tool: name] arg (without closing tag)
    for m in re.finditer(r"\[tool:\s*(\w+)\]\s*(.+?)(?:\n|$)", text):
        name = m.group(1).lower()
        arg = m.group(2).strip()
        if name not in ("write",) and not any(c[0] == name and c[1] == arg for c in calls):
            if not any(c[0] == name for c in calls):
                calls.append((name, arg, ""))
    seen = set()
    unique = []
    for c in calls:
        key = (c[0], c[1])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique

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
        self.msg_queue = queue.Queue()
        self.scroll_offset = 0
        self.chat_list = load_chat_history()
        self.mode = "chat"
        self.history_idx = 0
        self.status_msg = ""
        self.status_time = 0
        self.input_buf = ""
        self.input_pos = 0
        self.project_files = self._scan_project()

        curses.curs_set(1)
        curses.use_default_colors()
        self._init_colors()
        self.stdscr.keypad(True)
        self.height, self.width = stdscr.getmaxyx()
        self.content_h = self.height - 6

    def _init_colors(self):
        for i, c in [(1, curses.COLOR_CYAN), (2, curses.COLOR_GREEN), (3, curses.COLOR_YELLOW),
                      (4, curses.COLOR_RED), (5, curses.COLOR_MAGENTA)]:
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
        status = "🌐 Connected" if self.api_key else "⚠️ No Key"
        w = self.get_model_count()
        md = self.model.split("/")[-1][:20]
        left = f"  🤖 AI Chat  │  {md}"
        right = f"{status}  │  {w} models  "
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
                lines.append((1, f"  AI ({ts}):"))
                text = self.stream_buffer if (self.streaming and msg.get("_streaming")) else content
                for l in text.split("\n"): lines.append((-1, f"    {l}"))

        if self.streaming:
            status_text = "  ..."
            if self.status_msg and "stalled" in self.status_msg.lower():
                status_text = f"  ⚠️ switching..."
            if not lines or lines[-1][1] != status_text:
                lines.append((3, status_text))
            else:
                lines[-1] = (3, status_text)

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

    def add_message(self, role, content):
        entry = {"role": role, "content": content, "ts": time.strftime("%H:%M")}
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
            parts = arg.rsplit(" ", 1)
            return tool_grep(parts[0], parts[1] if len(parts) > 1 else None)
        if name == "glob": return tool_glob(arg)
        return f"Unknown tool: {name}"

    def _agent_loop(self, initial_msgs):
        """Multi-turn: AI responds, we run tools, feed results back, repeat."""
        max_turns = 5
        msgs = list(initial_msgs)
        for turn in range(max_turns):
            full = ""
            self.streaming = True
            self.stream_buffer = ""
            stalled_models = []
            q = queue.Queue()
            t = threading.Thread(target=self._stream, args=(msgs, q), daemon=True)
            t.start()
            last_chunk_time = time.monotonic()
            while True:
                try:
                    ev = q.get(timeout=0.1)
                    if ev["type"] == "chunk":
                        full += ev["content"]
                        self.stream_buffer = full
                        last_chunk_time = time.monotonic()
                    elif ev["type"] == "done":
                        full = ev.get("content", full)
                        self.model = ev.get("model", self.model)
                        self.streaming = False
                        break
                    elif ev["type"] == "stall":
                        model = ev.get("model", "?")
                        stalled_models.append(model)
                        reason = ev.get("reason", "")
                        self.set_status(f"⚠️ {model.split('/')[-1]} stalled — switching...")
                        self.stream_buffer = f"\n  ⚠️ {model.split('/')[-1]} stalled ({reason}), trying next model..."
                        if self.conversation and self.conversation[-1].get("_streaming"):
                            self.conversation[-1]["content"] = self.stream_buffer
                        self.refresh()
                    elif ev["type"] == "error":
                        self.streaming = False
                        self.set_status(f"❌ {ev.get('error','')}")
                        return full
                except queue.Empty:
                    if not self.streaming:
                        break
                    idle = time.monotonic() - last_chunk_time
                    if idle > 10 and self.streaming:
                        self.set_status("⚠️ Response delayed — still waiting...")
                        self.refresh()

            if self.conversation and self.conversation[-1].get("_streaming"):
                self.conversation[-1]["content"] = full
                self.conversation[-1]["_streaming"] = False
                self.conversation[-1]["model"] = self.model
            self.stream_buffer = ""

            tool_calls = parse_tool_calls(full)
            if not tool_calls:
                return full

            for name, arg, content in tool_calls:
                self.set_status(f"🛠 {name} {arg[:30]}...")
                self.refresh()
                result = self._run_tool(name, arg, content)
                sys_msg = f"[tool result: {name} {arg}]\n{result[:2000]}"
                msgs.append({"role": "assistant", "content": full})
                msgs.append({"role": "system", "content": sys_msg})
                if name == "write":
                    self.set_status(f"✅ Created {arg}")
                elif name == "bash":
                    rc = "0"
                    if result.startswith("exit "):
                        rc = result.split()[2] if len(result.split()) > 2 else "?"
                    self.set_status(f"✅ Command done (exit {rc})")
            if tool_calls:
                continue
            return full

        return full

    def _stream(self, msgs, q):
        models = get_working_models()
        candidates = list(dict.fromkeys(models + PREFERRED_MODELS + ["openrouter/free"]))
        for model in candidates:
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
                resp = urllib.request.urlopen(req, timeout=30)
                sock = resp.fp.raw
                if hasattr(sock, "_sock"): sock = sock._sock
                q.put({"type": "model_active", "model": model})
                full = ""
                got_first = False
                last_token_time = time.monotonic()
                start_time = time.monotonic()
                buffer = b""

                while True:
                    ready = select.select([sock], [], [], 1.0)
                    now = time.monotonic()
                    if ready[0]:
                        try:
                            chunk = resp.read(1)
                        except: break
                        if not chunk: break
                        buffer += chunk
                        if b"\n" in buffer:
                            lines = buffer.split(b"\n")
                            buffer = lines.pop()
                            for line in lines:
                                decoded = line.decode().strip()
                                if decoded.startswith("data: "):
                                    raw = decoded[6:]
                                    if raw == "[DONE]":
                                        q.put({"type": "done", "content": full, "model": model})
                                        elapsed_ms = int((now - start_time) * 1000)
                                        record_latency(model, full_ms=elapsed_ms)
                                        return
                                    try:
                                        data = json.loads(raw)
                                        delta = data.get("choices", [{}])[0].get("delta", {})
                                        content = delta.get("content", "")
                                        if content:
                                            if not got_first:
                                                got_first = True
                                                ttft_ms = int((now - start_time) * 1000)
                                                record_latency(model, ttft=ttft_ms)
                                            full += content
                                            last_token_time = now
                                            q.put({"type": "chunk", "content": content})
                                    except: pass
                    else:
                        elapsed = now - start_time
                        if not got_first:
                            if elapsed > FIRST_TOKEN_TIMEOUT:
                                penalize_model(model)
                                q.put({"type": "stall", "model": model, "reason": "no_first_token"})
                                break
                        else:
                            idle = now - last_token_time
                            if idle > STREAM_HANG_TIMEOUT:
                                penalize_model(model)
                                q.put({"type": "stall", "model": model, "reason": "stream_hang"})
                                break
                # If we broke out of loop due to stall, continue to next model
                continue
            except urllib.error.HTTPError as e:
                if e.code in (429, 503, 502):
                    q.put({"type": "stall", "model": model, "reason": f"HTTP {e.code}"})
                    continue
                q.put({"type": "error", "error": f"HTTP {e.code}"})
                return
            except (OSError, urllib.error.URLError) as e:
                q.put({"type": "stall", "model": model, "reason": "connection_error"})
                continue
            except Exception as e:
                q.put({"type": "stall", "model": model, "reason": "error"})
                continue
        q.put({"type": "error", "error": "All models exhausted"})

    def send_message(self, text):
        if not text.strip() or self.streaming: return
        if not self.api_key: return self.set_status("❌ No API key")

        self.add_message("user", text.strip())
        self.streaming = True
        ts = time.strftime("%H:%M")
        self.conversation.append({"role": "assistant", "content": "", "ts": ts, "_streaming": True})
        self.scroll_offset = max(0, self._total_lines() - self.content_h)
        self.set_status("⏳ Waiting for response...")

        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in self.conversation:
            if m.get("_streaming"): continue
            msgs.append({"role": m["role"], "content": m["content"]})

        # Run agent loop in background thread
        def agent_worker():
            result = self._agent_loop(msgs)
            self.streaming = False
            if self.conversation and self.conversation[-1].get("_streaming"):
                self.conversation[-1]["content"] = result
                self.conversation[-1]["_streaming"] = False
            save_chat_session({
                "id": self.current_chat_id,
                "model": self.model,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "messages": [{"role": m["role"], "content": m["content"]} for m in self.conversation if not m.get("_streaming")],
            })
            self.chat_list = load_chat_history()
            self.set_status(f"✅ {self.model.split('/')[-1]}")

        threading.Thread(target=agent_worker, daemon=True).start()

    def handle_stream_events(self):
        pass  # Streaming is now handled inside _agent_loop

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
        self.mode = "chat"
        self.scroll_offset = max(0, self._total_lines() - self.content_h)
        self.set_status(f"📜 Loaded from {c.get('timestamp','')[:10]}")

    # ---- Commands ----

    def handle_command(self, cmd):
        parts = cmd.split()
        c = parts[0].lower()
        if c == "/exit": raise KeyboardInterrupt
        elif c == "/clear":
            self.conversation = []; self.stream_buffer = ""; self.scroll_offset = 0; self.set_status("✅ Cleared")
        elif c == "/model":
            self.set_status(f"🧠 {self.model} ({self.get_model_count()} models)")
        elif c == "/models":
            ms = get_working_models()
            self.set_status(f"📊 {', '.join(m.split('/')[-1][:15] for m in ms[:5])}")
        elif c == "/key":
            if len(parts) > 1:
                self.api_key = parts[1]
                KEY_FILE.write_text(json.dumps({"key": parts[1], "saved": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2))
                self.set_status("✅ API key saved")
            else:
                self.set_status(f"🔑 {self.api_key[:12]}..." if self.api_key else "⚠️ No key")
        elif c == "/write":
            if len(parts) < 2: return self.set_status("⚠️ /write <path>")
            last = self.conversation[-1]["content"] if self.conversation else ""
            code = ""
            for m in re.finditer(r"```(\w+)?\n(.*?)```", last, re.DOTALL):
                code = m.group(2).strip()
            if not code: return self.set_status("⚠️ No code block in last response")
            fpath = " ".join(parts[1:])
            target = Path(fpath)
            if not target.is_absolute(): target = PROJECTS / target
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code)
            self.set_status(f"✅ Created {target}")
        elif c == "/read":
            if len(parts) < 2: return self.set_status("⚠️ /read <path>")
            fpath = " ".join(parts[1:])
            self.set_status(tool_read(fpath)[:self.width-10])
        elif c == "/run":
            if len(parts) < 2: return self.set_status("⚠️ /run <command>")
            cmd = " ".join(parts[1:])
            result = tool_bash(cmd)
            self.add_message("system", f"$ {cmd}\n{result[:500]}")
            self.set_status(f"✅ Exit {result.split()[2] if result.startswith('exit ') else '0'}")
        elif c == "/project":
            self.set_status(f"📁 {len(self.project_files)} files in Projects/")
        elif c == "/help":
            self.set_status("/exit /clear /model /models /key /write <path> /read <path> /run <cmd> /project")
        else:
            self.set_status(f"❌ Unknown: {c}")

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
