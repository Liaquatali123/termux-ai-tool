#!/usr/bin/env python3
"""chat_app.py — Web-based AI chat application with OpenRouter backend."""

import sys, json, os, time, threading, urllib.request, urllib.error
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from datetime import datetime
import urllib.parse

sys.path.insert(0, str(Path(__file__).parent))
from storage_manager import AI

API_BASE = "https://openrouter.ai/api/v1/chat/completions"
KEY_FILE = AI / "configs" / "api_key.json"
CONFIG = AI / "configs" / "models_config.json"
CHAT_HISTORY = AI / "configs" / "chat_history.json"
WEB_DIR = Path(__file__).parent / "web"
PORT = 8080

def load_api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key and KEY_FILE.exists():
        try:
            key = json.loads(KEY_FILE.read_text()).get("key", "")
        except: pass
    return key

def save_api_key(key):
    KEY_FILE.write_text(json.dumps({"key": key, "saved": datetime.now().isoformat()}, indent=2))
    os.environ["OPENROUTER_API_KEY"] = key

def load_config():
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text())
        except: pass
    return {}

def get_working_models():
    cfg = load_config()
    models = cfg.get("working_models", [])
    if not models:
        models = cfg.get("fallback_order", ["openrouter/free"])
    return models

def get_active_model():
    models = get_working_models()
    return models[0] if models else "openrouter/free"

def load_history():
    if CHAT_HISTORY.exists():
        try:
            return json.loads(CHAT_HISTORY.read_text())
        except: pass
    return []

def save_history(history):
    CHAT_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    CHAT_HISTORY.write_text(json.dumps(history, indent=2))

def resolve_image_data(msg):
    if not isinstance(msg.get("content"), list):
        return msg
    content = []
    for part in msg["content"]:
        if isinstance(part, dict) and part.get("type") == "image_url":
            url = part.get("image_url", {}).get("url", "")
            if url.startswith("data:image/"):
                content.append(part)
            else:
                continue
        else:
            content.append(part)
    return {**msg, "content": content}

def stream_chat_completion(messages, api_key):
    models = get_working_models()
    candidates = models + ["openrouter/free"]
    used = set()

    for model in candidates:
        if model in used:
            continue
        used.add(model)

        safe_msgs = []
        for m in messages:
            safe_msgs.append(resolve_image_data(m))

        payload = json.dumps({
            "model": model,
            "messages": safe_msgs,
            "stream": True,
            "max_tokens": 4096,
            "temperature": 0.7,
        }).encode()

        req = urllib.request.Request(
            API_BASE, data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Liaquatali123/termux-ai-tool",
                "X-Title": "Termux AI Chat",
            }
        )

        try:
            resp = urllib.request.urlopen(req, timeout=120)
            yield {"type": "meta", "model": model}
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
                            yield {"type": "chunk", "content": content}
                    except json.JSONDecodeError:
                        pass
            yield {"type": "done", "content": full, "model": model}
            return
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 502):
                continue
            yield {"type": "error", "error": f"HTTP {e.code}", "model": model}
            return
        except Exception as e:
            continue

    yield {"type": "error", "error": "All models exhausted"}

# ------- HTTP Server -------

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

class ChatHandler(BaseHTTPRequestHandler):
    server_version = "TermuxAIChat/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._serve_file("index.html", "text/html; charset=utf-8")
        elif path == "/api/models":
            self._handle_models()
        elif path == "/api/status":
            self._handle_status()
        elif path == "/api/history":
            self._handle_get_history()
        elif path.startswith("/api/history/"):
            self._handle_delete_history()
        else:
            static_ext = {".css": "text/css", ".js": "application/javascript", ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"}
            ext = Path(path).suffix
            if ext in static_ext:
                self._serve_file(path.lstrip("/"), static_ext[ext])
            else:
                self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/chat":
            self._handle_chat_stream()
        elif path == "/api/history":
            self._handle_save_history()
        elif path == "/api/key":
            self._handle_set_key()
        else:
            self.send_error(404)

    def do_DELETE(self):
        if self.path.startswith("/api/history/"):
            self._handle_delete_history()
        else:
            self.send_error(404)

    def _serve_file(self, rel, mime):
        filepath = WEB_DIR / rel
        if not filepath.exists() or not filepath.is_file():
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self._send_cors()
        self.end_headers()
        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors()
        self.end_headers()
        self.wfile.write(body)

    def _handle_models(self):
        cfg = load_config()
        working = cfg.get("working_models", [])
        details = cfg.get("model_details", {})
        active = get_active_model()
        self._send_json({
            "active": active,
            "models": working,
            "details": {m: details.get(m, {}) for m in working},
            "fallback": cfg.get("fallback_order", []),
        })

    def _handle_status(self):
        api_key = load_api_key()
        from daemon_manager import get_pid
        pid = get_pid()
        self._send_json({
            "api_key_set": bool(api_key),
            "scanner_pid": pid or None,
            "scanner_running": bool(pid),
            "model_count": len(get_working_models()),
        })

    def _handle_get_history(self):
        hist = load_history()
        summary = []
        for h in hist:
            msgs = h.get("messages", [])
            first = ""
            for m in msgs:
                if m.get("role") == "user":
                    c = m.get("content", "")
                    if isinstance(c, str):
                        first = c[:80]
                    break
            summary.append({
                "id": h.get("id", ""),
                "title": first or "New Chat",
                "timestamp": h.get("timestamp", ""),
                "model": h.get("model", ""),
                "message_count": len(msgs),
            })
        self._send_json(summary)

    def _handle_save_history(self):
        data = self._read_body()
        hist = load_history()
        chat_id = data.get("id", datetime.now().strftime("%Y%m%d_%H%M%S"))
        entry = {
            "id": chat_id,
            "timestamp": datetime.now().isoformat(),
            "model": data.get("model", get_active_model()),
            "messages": data.get("messages", []),
        }
        existing = [h for h in hist if h.get("id") != chat_id]
        existing.append(entry)
        save_history(existing[-20:])
        self._send_json({"saved": True, "id": chat_id})

    def _handle_delete_history(self):
        chat_id = self.path.split("/")[-1]
        hist = load_history()
        hist = [h for h in hist if h.get("id") != chat_id]
        save_history(hist)
        self._send_json({"deleted": True})

    def _handle_set_key(self):
        data = self._read_body()
        key = data.get("key", "")
        if key:
            save_api_key(key)
            self._send_json({"saved": True})
        else:
            self._send_json({"error": "No key provided"}, 400)

    def _handle_chat_stream(self):
        data = self._read_body()
        messages = data.get("messages", [])
        api_key = data.get("key", load_api_key())

        if not api_key:
            self._send_json({"error": "No API key"}, 401)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._send_cors()
        self.end_headers()

        for event in stream_chat_completion(messages, api_key):
            line = f"data: {json.dumps(event)}\n\n"
            try:
                self.wfile.write(line.encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break


def start_server(port=PORT, host="0.0.0.0"):
    server = ThreadingHTTPServer((host, port), ChatHandler)
    print(f"  🌐 AI Chat: http://localhost:{port}")
    print(f"  📱 Network:  http://{host}:{port}")
    print(f"  🛑 Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
        server.shutdown()

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    start_server(args.port, args.host)

if __name__ == "__main__":
    main()
