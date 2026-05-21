#!/usr/bin/env python3
"""tui_chat.py — Full-screen Terminal AI Chat (curses TUI)."""

import sys, json, os, time, threading, queue, urllib.request, urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from storage_manager import AI

API_BASE = "https://openrouter.ai/api/v1/chat/completions"
CONFIG = AI / "configs" / "models_config.json"
KEY_FILE = AI / "configs" / "api_key.json"
CHAT_HISTORY = AI / "configs" / "chat_history.json"
PROJECTS = AI.parent / "Projects"
CWD = Path.cwd()

SYSTEM_PROMPT = """You are an AI coding assistant running in Termux on Android as part of termux-ai-tool. You act like OpenCode — a terminal-native AI for developers.

## Your identity
- You are a coding expert, not a general chatbot
- You live in a terminal environment (Termux on Android)
- You work with Python, JavaScript, Shell, and common languages
- You are practical and action-oriented

## Response style
- **Concise by default**: give the answer directly, add detail only when needed
- **Code-first**: always show code in ```language blocks
- **Commands**: prefix shell commands with `$ ` or use ```bash
- **Diffs**: show file path and changes when editing
- **No padding**: skip "I understand your question" / "Here's how you can..." / "One approach is..."
- **Natural**: talk like a developer pairing with you, not a textbook

## Examples of good responses
- User: "make a python test file for this function" → show the file content with ```python, say where to save it
- User: "fix this error: TypeError: X is not a function" → show the fix with diff, explain briefly
- User: "how does this work?" → 2-3 sentence explanation + code

## Context
- Project root: """ + str(PROJECTS) + """
- AI backend: """ + str(AI) + """
- Current working dir: """ + str(CWD) + """
- You use OpenRouter free models with auto-failover
- You can suggest file paths relative to the project"""

# ---- Shared Engine (same logic as before, no web deps) ----

def load_api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key and KEY_FILE.exists():
        try:
            key = json.loads(KEY_FILE.read_text()).get("key", "")
        except: pass
    return key

def get_working_models():
    try:
        cfg = json.loads(CONFIG.read_text())
        return cfg.get("working_models", cfg.get("fallback_order", ["openrouter/free"]))
    except:
        return ["openrouter/free"]

def get_active_model():
    models = get_working_models()
    return models[0] if models else "openrouter/free"

def stream_chat(messages, api_key, result_queue):
    """Background thread: streams chunks into result_queue."""
    models = get_working_models()
    candidates = list(dict.fromkeys(models + ["openrouter/free"]))
    result_queue.put({"type": "meta", "models": candidates})

    for model in candidates:
        payload = json.dumps({
            "model": model, "messages": messages,
            "stream": True, "max_tokens": 4096, "temperature": 0.7,
        }).encode()
        req = urllib.request.Request(
            API_BASE, data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Liaquatali123/termux-ai-tool",
                "X-Title": "Termux AI",
            }
        )
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            result_queue.put({"type": "model_active", "model": model})
            full = ""
            while True:
                line = resp.readline()
                if not line:
                    break
                decoded = line.decode().strip()
                if decoded.startswith("data: "):
                    raw = decoded[6:]
                    if raw == "[DONE]":
                        break
                    try:
                        data = json.loads(raw)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full += content
                            result_queue.put({"type": "chunk", "content": content})
                    except json.JSONDecodeError:
                        pass
            result_queue.put({"type": "done", "content": full, "model": model})
            return
        except urllib.error.HTTPError as e:
            result_queue.put({"type": "fail", "model": model, "code": e.code})
            if e.code not in (429, 503, 502):
                result_queue.put({"type": "error", "error": f"HTTP {e.code}"})
                return
        except Exception as e:
            result_queue.put({"type": "fail", "model": model, "code": 0})
    result_queue.put({"type": "error", "error": "All models exhausted"})

def load_chat_history():
    if CHAT_HISTORY.exists():
        try:
            return json.loads(CHAT_HISTORY.read_text())
        except: pass
    return []

def save_chat_session(session):
    CHAT_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    hist = load_chat_history()
    hist = [h for h in hist if h.get("id") != session.get("id")]
    hist.append(session)
    CHAT_HISTORY.write_text(json.dumps(hist[-20:], indent=2))

# ---- Curses TUI ----

import curses
import curses.textpad

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
        self.thread = None
        self.scroll_offset = 0
        self.chat_list = load_chat_history()
        self.mode = "chat"  # "chat" | "history"
        self.history_idx = 0
        self.status_msg = ""
        self.status_time = 0

        curses.curs_set(1)
        curses.use_default_colors()
        self.init_colors()
        self.stdscr.keypad(True)

        self.height, self.width = stdscr.getmaxyx()
        self.header_h = 2
        self.input_h = 3
        self.help_h = 1
        self.content_h = self.height - self.header_h - self.input_h - self.help_h

        self.input_buf = ""
        self.input_pos = 0
        self.last_code_block = ""
        self.project_files = self._scan_project()

    def _scan_project(self):
        files = []
        if PROJECTS.exists():
            for f in sorted(PROJECTS.rglob("*"))[:50]:
                if f.is_file() and f.suffix in (".py", ".js", ".sh", ".json", ".md", ".txt", ".html", ".css"):
                    try:
                        rel = f.relative_to(PROJECTS)
                        files.append(str(rel))
                    except: pass
        return files

    def init_colors(self):
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_RED, -1)
        curses.init_pair(5, curses.COLOR_MAGENTA, -1)
        curses.init_pair(6, curses.COLOR_BLUE, -1)
        curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_WHITE)
        self.C_CYAN = 1
        self.C_GREEN = 2
        self.C_YELLOW = 3
        self.C_RED = 4
        self.C_MAGENTA = 5
        self.C_BLUE = 6
        self.C_HEADER = 7
        self.C_INPUT = 8

    def get_model_count(self):
        return len(get_working_models())

    def draw_header(self):
        h = self.header_h
        status = "🌐 Connected" if self.api_key else "⚠️ No Key"
        w_count = self.get_model_count()
        model_display = self.model.split("/")[-1][:20] if "/" in self.model else self.model[:20]
        left = f"  🤖 AI Chat  │  {model_display}"
        right = f"{status}  │  {w_count} models  "
        line = left + " " * (self.width - len(left) - len(right)) + right
        self.stdscr.attron(curses.color_pair(self.C_HEADER) | curses.A_BOLD)
        self.stdscr.addstr(0, 0, line[:self.width])
        self.stdscr.attroff(curses.color_pair(self.C_HEADER) | curses.A_BOLD)
        sep = "─" * self.width
        self.stdscr.attron(curses.color_pair(self.C_CYAN) | curses.A_DIM)
        self.stdscr.addstr(1, 0, sep[:self.width])
        self.stdscr.attroff(curses.color_pair(self.C_CYAN) | curses.A_DIM)

    def draw_content(self):
        content_top = self.header_h
        content_h = self.content_h
        stdscr = self.stdscr

        # Clear content area
        for y in range(content_h):
            stdscr.addstr(content_top + y, 0, " " * self.width)

        if self.mode == "history":
            self.draw_history_list(content_top, content_h)
            return

        # Build display lines from conversation
        lines = []
        for msg in self.conversation:
            role = msg.get("role", "")
            content = msg.get("content", "")
            ts = msg.get("ts", "")
            if isinstance(content, list):
                continue
            if role == "user":
                lines.append(("user", f"  You ({ts}):", self.C_GREEN))
                for line in content.split("\n"):
                    lines.append(("user", f"    {line}", -1))
            elif role == "assistant":
                lines.append(("assistant", f"  AI ({ts}):", self.C_CYAN))
                text = content
                if self.streaming and msg.get("_streaming"):
                    text = self.stream_buffer
                for line in text.split("\n"):
                    lines.append(("assistant", f"    {line}", -1))

        # Streaming indicator
        if self.streaming:
            if not lines or lines[-1][1] != "  ...":
                lines.append(("system", "  ...", self.C_YELLOW))
            else:
                lines[-1] = ("system", "  ...", self.C_YELLOW)

        # Adjust scroll
        total_lines = len(lines)
        max_scroll = max(0, total_lines - content_h)
        if self.scroll_offset > max_scroll:
            self.scroll_offset = max_scroll

        start = self.scroll_offset
        end = start + content_h
        visible = lines[start:end]

        for i, (tag, text, color) in enumerate(visible):
            y = content_top + i
            try:
                if color > 0:
                    stdscr.attron(curses.color_pair(color) | (curses.A_BOLD if tag == "user" else curses.A_NORMAL))
                    stdscr.addstr(y, 0, text[:self.width])
                    stdscr.attroff(curses.color_pair(color) | (curses.A_BOLD if tag == "user" else curses.A_NORMAL))
                else:
                    stdscr.addstr(y, 0, text[:self.width])
            except curses.error:
                pass

        # Scroll indicator
        if max_scroll > 0:
            pct = int((self.scroll_offset / max_scroll) * 100) if max_scroll else 0
            indicator = f"  ↑ {pct}% scroll"
            try:
                stdscr.attron(curses.color_pair(self.C_YELLOW) | curses.A_DIM)
                stdscr.addstr(content_top + content_h - 1, max(0, self.width - len(indicator) - 2), indicator)
                stdscr.attroff(curses.color_pair(self.C_YELLOW) | curses.A_DIM)
            except curses.error:
                pass

    def draw_history_list(self, top, h):
        stdscr = self.stdscr
        chats = self.chat_list
        if not chats:
            stdscr.addstr(top, 2, "No saved chats", curses.color_pair(self.C_YELLOW))
            return

        stdscr.addstr(top, 2, "Saved Chats:", curses.A_BOLD)
        for i, c in enumerate(chats[-h+1:]):
            y = top + 1 + i
            if y >= top + h:
                break
            title = c.get("messages", [{}])[0].get("content", "New Chat")[:50] if c.get("messages") else "New Chat"
            if isinstance(title, list):
                title = "New Chat"
            ts = c.get("timestamp", "")[5:19] if c.get("timestamp") else ""
            marker = ">" if i == self.history_idx else " "
            try:
                attr = curses.A_REVERSE if i == self.history_idx else curses.A_NORMAL
                stdscr.addstr(y, 2, f"{marker} {title[:self.width-10]}  {ts}", attr)
            except curses.error:
                pass

    def draw_input(self):
        y = self.height - self.help_h - self.input_h
        # Input box border
        try:
            self.stdscr.attron(curses.color_pair(self.C_CYAN) | curses.A_DIM)
            self.stdscr.addstr(y, 0, "─" * self.width)
            self.stdscr.attroff(curses.color_pair(self.C_CYAN) | curses.A_DIM)
        except: pass

        # Prompt
        prompt = "> "
        inp_y = y + 1
        try:
            self.stdscr.attron(curses.color_pair(self.C_GREEN) | curses.A_BOLD)
            self.stdscr.addstr(inp_y, 0, prompt)
            self.stdscr.attroff(curses.color_pair(self.C_GREEN) | curses.A_BOLD)
        except: pass

        # Input text
        max_w = self.width - len(prompt) - 1
        display = self.input_buf[:max_w]
        try:
            self.stdscr.attron(curses.color_pair(self.C_INPUT))
            self.stdscr.addstr(inp_y, len(prompt), display + " " * (max_w - len(display)))
            self.stdscr.attroff(curses.color_pair(self.C_INPUT))
        except: pass

        # Cursor position
        cursor_x = len(prompt) + min(self.input_pos, max_w)
        self.stdscr.move(inp_y, cursor_x)

        # Status message
        status_y = self.height - self.help_h
        if self.status_msg and time.time() - self.status_time < 3:
            try:
                self.stdscr.attron(curses.color_pair(self.C_YELLOW))
                self.stdscr.addstr(status_y, 0, f"  {self.status_msg[:self.width-4]}")
                self.stdscr.attroff(curses.color_pair(self.C_YELLOW))
            except: pass
        else:
            try:
                hints = "Ctrl+N:New  Ctrl+L:Clear  Ctrl+H:History  /write <path>  Esc:Exit"
                self.stdscr.attron(curses.A_DIM)
                self.stdscr.addstr(status_y, 0, f"  {hints[:self.width-4]}")
                self.stdscr.attroff(curses.A_DIM)
            except: pass

    def refresh(self):
        self.stdscr.erase()
        self.height, self.width = self.stdscr.getmaxyx()
        self.content_h = self.height - self.header_h - self.input_h - self.help_h
        self.draw_header()
        self.draw_content()
        self.draw_input()
        self.stdscr.noutrefresh()
        curses.doupdate()

    def set_status(self, msg):
        self.status_msg = msg
        self.status_time = time.time()

    def add_message(self, role, content):
        ts = time.strftime("%H:%M")
        entry = {"role": role, "content": content, "ts": ts}
        self.conversation.append(entry)
        self.scroll_offset = max(0, self._total_lines() - self.content_h)
        return entry

    def _total_lines(self):
        count = 0
        for msg in self.conversation:
            count += 2  # header line
            content = msg.get("content", "")
            count += content.count("\n") + 1
        return count

    def send_message(self, text):
        if not text.strip() or self.streaming:
            return
        if not self.api_key:
            self.set_status("❌ No API key — use: termux-ai key <token>")
            return

        self.add_message("user", text.strip())
        self.streaming = True
        self.stream_buffer = ""

        # Add placeholder assistant message
        ts = time.strftime("%H:%M")
        self.conversation.append({"role": "assistant", "content": "", "ts": ts, "_streaming": True})
        self.scroll_offset = max(0, self._total_lines() - self.content_h)

        # Build message list for API — always prepend system prompt
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in self.conversation:
            if m.get("_streaming"):
                continue
            msgs.append({"role": m["role"], "content": m["content"]})

        self.msg_queue = queue.Queue()
        self.thread = threading.Thread(target=stream_chat, args=(msgs, self.api_key, self.msg_queue), daemon=True)
        self.thread.start()

    def handle_stream_events(self):
        if not self.streaming:
            return
        try:
            while True:
                ev = self.msg_queue.get_nowait()
                t = ev.get("type")

                if t == "chunk":
                    self.stream_buffer += ev.get("content", "")
                elif t == "done":
                    content = ev.get("content", self.stream_buffer)
                    model = ev.get("model", self.model)
                    self.model = model
                    self.streaming = False
                    self.stream_buffer = ""

                    # Update assistant message
                    if self.conversation and self.conversation[-1].get("_streaming"):
                        self.conversation[-1]["content"] = content
                        self.conversation[-1]["_streaming"] = False
                        self.conversation[-1]["model"] = model

                    # Save
                    save_chat_session({
                        "id": self.current_chat_id,
                        "model": model,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "messages": [
                            {"role": m["role"], "content": m["content"]}
                            for m in self.conversation if not m.get("_streaming")
                        ],
                    })
                    self.chat_list = load_chat_history()
                    self.set_status(f"✅ Model: {model.split('/')[-1]}")

                elif t == "error":
                    self.streaming = False
                    self.stream_buffer = ""
                    if self.conversation and self.conversation[-1].get("_streaming"):
                        self.conversation[-1]["content"] = f"[Error: {ev.get('error','')}]"
                        self.conversation[-1]["_streaming"] = False
                    self.set_status(f"❌ {ev.get('error','')}")

                elif t == "model_active":
                    self.set_status(f"🔄 Trying: {ev['model'].split('/')[-1]}...")

                elif t == "fail":
                    pass

        except queue.Empty:
            pass

    def toggle_history(self):
        if self.mode == "chat":
            self.mode = "history"
            self.history_idx = 0
        else:
            self.mode = "chat"

    def load_chat_from_history(self, idx):
        chats = self.chat_list
        if not chats or idx >= len(chats):
            return
        c = chats[-(idx+1)]
        self.conversation = []
        for m in c.get("messages", []):
            self.conversation.append({
                "role": m["role"],
                "content": m["content"],
                "ts": c.get("timestamp", "")[11:16] if c.get("timestamp") else "",
            })
        self.current_chat_id = c.get("id", f"chat_{int(time.time())}")
        self.model = c.get("model", self.model)
        self.mode = "chat"
        self.scroll_offset = max(0, self._total_lines() - self.content_h)
        self.set_status(f"📜 Loaded chat from {c.get('timestamp','')[:10]}")

    def run(self):
        while True:
            self.handle_stream_events()
            self.refresh()

            key = self.stdscr.getch()

            if key == 27:  # Escape
                break

            elif key == curses.KEY_RESIZE:
                continue

            elif key == 10 or key == curses.KEY_ENTER:  # Enter
                if self.mode == "history":
                    self.load_chat_from_history(self.history_idx)
                elif self.input_buf.strip().startswith("/"):
                    self.handle_command(self.input_buf.strip())
                    self.input_buf = ""
                    self.input_pos = 0
                else:
                    self.send_message(self.input_buf)
                    self.input_buf = ""
                    self.input_pos = 0

            elif key == curses.KEY_BACKSPACE or key == 127:
                if self.input_pos > 0:
                    self.input_buf = self.input_buf[:self.input_pos-1] + self.input_buf[self.input_pos:]
                    self.input_pos -= 1

            elif key == 21:  # Ctrl+U - clear input
                self.input_buf = ""
                self.input_pos = 0

            elif key == curses.KEY_LEFT:
                if self.input_pos > 0:
                    self.input_pos -= 1

            elif key == curses.KEY_RIGHT:
                if self.input_pos < len(self.input_buf):
                    self.input_pos += 1

            elif key == curses.KEY_HOME:
                self.input_pos = 0

            elif key == curses.KEY_END:
                self.input_pos = len(self.input_buf)

            elif key == curses.KEY_UP:
                if self.mode == "history":
                    self.history_idx = min(self.history_idx + 1, len(self.chat_list) - 1)
                else:
                    if self.scroll_offset > 0:
                        self.scroll_offset -= 1

            elif key == curses.KEY_DOWN:
                if self.mode == "history":
                    self.history_idx = max(self.history_idx - 1, 0)
                else:
                    max_s = max(0, self._total_lines() - self.content_h)
                    if self.scroll_offset < max_s:
                        self.scroll_offset += 1

            elif key == curses.KEY_PPAGE:
                self.scroll_offset = max(0, self.scroll_offset - self.content_h)

            elif key == curses.KEY_NPAGE:
                max_s = max(0, self._total_lines() - self.content_h)
                self.scroll_offset = min(max_s, self.scroll_offset + self.content_h)

            elif key == 12:  # Ctrl+L - clear
                self.conversation = []
                self.stream_buffer = ""
                self.scroll_offset = 0
                self.set_status("✅ Conversation cleared")

            elif key == 14:  # Ctrl+N - new chat
                self.conversation = []
                self.current_chat_id = f"chat_{int(time.time())}"
                self.stream_buffer = ""
                self.scroll_offset = 0
                self.set_status("✅ New chat started")

            elif key == 8:  # Ctrl+H - history
                self.toggle_history()

            elif key == 3:  # Ctrl+C
                break

            elif 32 <= key <= 255:
                char = chr(key)
                if self.mode == "chat":
                    self.input_buf = self.input_buf[:self.input_pos] + char + self.input_buf[self.input_pos:]
                    self.input_pos += 1

    def _extract_last_code_block(self, text):
        import re
        blocks = re.findall(r"```(\w+)?\n(.*?)```", text, re.DOTALL)
        if blocks:
            lang, code = blocks[-1]
            return code.strip()
        return ""

    def _write_file(self, path, content):
        target = Path(path)
        if not target.is_absolute():
            target = PROJECTS / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def handle_command(self, cmd):
        parts = cmd.split()
        c = parts[0].lower()

        if c == "/exit":
            raise KeyboardInterrupt
        elif c == "/clear":
            self.conversation = []
            self.stream_buffer = ""
            self.scroll_offset = 0
            self.set_status("✅ Cleared")
        elif c == "/model":
            self.set_status(f"🧠 {self.model} ({self.get_model_count()} models available)")
        elif c == "/models":
            ms = get_working_models()
            self.set_status(f"📊 Models: {', '.join(m.split('/')[-1][:15] for m in ms[:5])}")
        elif c == "/key":
            if len(parts) > 1:
                self.api_key = parts[1]
                KEY_FILE.write_text(json.dumps({"key": parts[1], "saved": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2))
                self.set_status("✅ API key saved")
            else:
                self.set_status(f"🔑 Key: {self.api_key[:12]}..." if self.api_key else "⚠️ No key")
        elif c == "/write":
            if len(parts) < 2:
                self.set_status("⚠️ Usage: /write <filepath>")
            else:
                self.last_code_block = self._extract_last_code_block(
                    self.conversation[-1]["content"] if self.conversation else ""
                )
                if not self.last_code_block:
                    self.set_status("⚠️ No code block found in last response")
                else:
                    fpath = " ".join(parts[1:])
                    target = self._write_file(fpath, self.last_code_block)
                    self.last_code_block = ""
                    self.set_status(f"✅ Created {target}")
        elif c == "/project":
            files = self.project_files
            if not files:
                self.set_status("📁 No project files found")
            else:
                self.set_status(f"📁 {len(files)} files (Ctrl+H to browse)")
        elif c == "/help":
            self.set_status("/exit /clear /model /models /key /write <path> /project /help")
        else:
            self.set_status(f"❌ Unknown: {c}")


def launch_tui():
    api_key = load_api_key()
    if not api_key:
        print("⚠️  No API key set — use: termux-ai key <token>")
        return

    try:
        curses.wrapper(lambda stdscr: TUIChat(stdscr).run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\nTUI error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    launch_tui()
