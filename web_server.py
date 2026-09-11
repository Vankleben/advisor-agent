"""
导师情报 Agent —— 极简本地 Web 聊天页（后端）
零新依赖：Python 内置 http.server + 复用 main.py 的 function calling 链路。
启动：python tools/web_server.py  → 浏览器 http://127.0.0.1:8080
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent          # web_server.py 在项目根目录
TOOLS_DIR = BASE_DIR / "tools"
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(TOOLS_DIR))

import main as agent                    # 复用 CLIENT / SYSTEM / TOOLS / DISPATCH


def _msg_to_dict(msg) -> dict:
    """把 OpenAI ChatCompletionMessage 转成 JSON 可序列化的 dict（供历史回传）。"""
    d = {"role": msg.role}
    if msg.content:
        d["content"] = msg.content
    if getattr(msg, "tool_calls", None):
        d["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls]
    return d


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass  # 静默访问日志

    def _send_json(self, obj: dict, code: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = (BASE_DIR / "web" / "index.html").read_text(encoding="utf-8")
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # 其他资源(若有)直接尝试读 web 目录
        try:
            f = (BASE_DIR / "web" / path.lstrip("/")).resolve()
            body = f.read_bytes()
            ct = {"css": "text/css; charset=utf-8", "js": "application/javascript",
                  "html": "text/html; charset=utf-8", "md": "text/plain; charset=utf-8"}.get(
                f.suffix.lstrip("."), "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if urlparse(self.path).path != "/chat":
            self._send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            # 会话状态：由前端维护 messages 历史，每次整段回传（简单可靠，不引数据库）
            messages = payload.get("messages", [])
            user_text = payload.get("message", "").strip()
            if not user_text:
                self._send_json({"error": "空消息"}, 400)
                return
            # 注入系统提示
            if not messages or messages[0].get("role") != "system":
                messages.insert(0, {"role": "system", "content": agent.SYSTEM})
            messages.append({"role": "user", "content": user_text})

            tool_log = []
            final_reply = ""
            # function calling 循环（复用 main.py 的 TOOLS/DISPATCH，机制同 CLI）
            for _ in range(10):
                resp = agent.CLIENT.chat.completions.create(
                    model=agent.P["fast"], messages=messages, tools=agent.TOOLS, temperature=0.3)
                msg = resp.choices[0].message
                if msg.tool_calls:
                    messages.append(_msg_to_dict(msg))
                    for call in msg.tool_calls:
                        args = json.loads(call.function.arguments or "{}")
                        log_entry = {"name": call.function.name, "args": str(args)[:200]}
                        try:
                            result = agent.DISPATCH[call.function.name](**args)
                            log_entry["preview"] = (result if isinstance(result, str)
                                                     else str(result))[:220]
                        except Exception as e:
                            tb = traceback.format_exc()[-400:]
                            result = json.dumps({"error": str(e), "traceback": tb},
                                                ensure_ascii=False)
                            log_entry["preview"] = f"异常：{e}"
                            log_entry["has_error"] = True
                        tool_log.append(log_entry)
                        messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
                else:
                    final_reply = msg.content or ""
                    messages.append(_msg_to_dict(msg))
                    break

            # 只回传 messages + 本次工具调用的简短记录
            return self._send_json({"reply": final_reply, "tools": tool_log,
                                    "messages": messages})
        except Exception as e:
            return self._send_json({"error": f"{e}\n{traceback.format_exc()[-500:]}"}, 500)


if __name__ == "__main__":
    PORT = 8080
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"✅ 导师情报 Agent Web 界面：http://127.0.0.1:{PORT}  （Ctrl+C 停止）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()