"""
会话历史：把每次终端会话记录到本地，关掉终端后也能回看。

存储：archive/chat_history/YYYY-MM-DD_HHMMSS.jsonl
      每行一条消息 {ts, role, text}；只留本地（archive/ 已在 .gitignore）

在 Agent 里使用：
  /history              列出最近会话（编号 / 时间 / 轮数 / 首句）
  /history 3            查看列表 #3 的完整对话
  /history latest       查看最近一次会话
  /history 关键词        在所有历史里搜索

在终端使用（不在 Agent 里时）：
  python tools/chat_history.py               列出
  python tools/chat_history.py show 3        查看 #3
  python tools/chat_history.py show latest
  python tools/chat_history.py search 关键词
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import sys
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
HIST_DIR = BASE_DIR / "archive" / "chat_history"

_current = None          # 当前会话文件（列表里标记"（当前）"）


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_session() -> Path:
    """开一个新会话：返回文件路径（首次写入时才真正建文件）。"""
    global _current
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    _current = HIST_DIR / (datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".jsonl")
    return _current


def append(session: Path, role: str, text: str) -> None:
    """追加一条消息；任何异常都静默（记录历史不应影响对话本身）。"""
    if not session or not text:
        return
    try:
        text = str(text)
        if len(text) > 50000:
            text = text[:50000] + "……（超长截断）"
        rec = {"ts": _now(), "role": role, "text": text}
        with open(session, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _read(path: Path) -> list:
    msgs = []
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                msgs.append(json.loads(ln))
            except Exception:
                continue
    except Exception:
        pass
    return msgs


def _sessions() -> list:
    """所有会话文件，按最后修改时间倒序（新的在前）"""
    if not HIST_DIR.exists():
        return []
    return sorted(HIST_DIR.glob("*.jsonl"),
                  key=lambda p: p.stat().st_mtime, reverse=True)


ROLE_NAME = {"user": "你", "assistant": "Agent"}


def _format(path: Path, msgs: list, max_per_msg: int = 2500) -> str:
    if not msgs:
        return f"（{path.stem} 是空会话）"
    n_q = sum(1 for m in msgs if m.get("role") == "user")
    out = [f"===== 会话 {path.stem}（{n_q} 问，共 {len(msgs)} 条）====="]
    for m in msgs:
        role = m.get("role", "?")
        text = str(m.get("text", ""))
        if len(text) > max_per_msg:
            text = text[:max_per_msg] + " ……（已截断，完整内容见文件）"
        ts = str(m.get("ts", ""))
        ts = ts[11:19] if len(ts) >= 19 else ts
        if role == "tool":
            out.append(f"[{ts}] 〔工具〕{text}")
        else:
            out.append(f"[{ts}] {ROLE_NAME.get(role, role)}：{text}")
    out.append(f"（文件：{path}）")
    return "\n".join(out)


def list_sessions() -> str:
    files = _sessions()
    if not files:
        return "还没有历史会话（从本次开始，每轮对话会自动记录到 archive/chat_history/）"
    lines = ["会话历史（新的在前）："]
    for i, f in enumerate(files, 1):
        msgs = _read(f)
        n_q = sum(1 for m in msgs if m.get("role") == "user")
        first = next((str(m.get("text", "")) for m in msgs if m.get("role") == "user"), "")
        preview = first.replace("\n", " ")[:34]
        mark = "（当前）" if f == _current else ""
        mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M")
        lines.append(f"  #{i}  {mtime}  {n_q} 问  「{preview}」{mark}")
    lines.append("查看：/history 编号（如 /history 1）或 /history latest；搜索：/history 关键词")
    return "\n".join(lines)


def show_session(arg: str) -> str:
    files = _sessions()
    if not files:
        return "还没有历史会话"
    if arg == "latest":
        idx = 1
    elif arg.isdigit():
        idx = int(arg)
    else:
        return f"不认识的参数：/history {arg}（可用：编号 / latest / 关键词）"
    if not (1 <= idx <= len(files)):
        return f"编号超出范围（当前共 {len(files)} 次会话，可用 1-{len(files)}）"
    f = files[idx - 1]
    return _format(f, _read(f))


def search(kw: str, limit: int = 30) -> str:
    hits = []
    for f in _sessions():
        for m in _read(f):
            text = str(m.get("text", ""))
            if kw.lower() in text.lower():
                hits.append((f, m))
    if not hits:
        return f"没有找到包含「{kw}」的记录"
    out = [f"包含「{kw}」的记录（共 {len(hits)} 条，显示前 {min(limit, len(hits))} 条）："]
    for f, m in hits[:limit]:
        role = ROLE_NAME.get(m.get("role"), m.get("role", "?"))
        text = str(m.get("text", "")).replace("\n", " ")
        i = text.lower().find(kw.lower())
        s = max(0, i - 40)
        snippet = text[s:i + len(kw) + 60]
        out.append(f"  [{f.stem}] {role}：…{snippet}…")
    return "\n".join(out)


def handle(arg: str) -> str:
    """处理 /history 的参数：'' → 列表；数字/latest → 查看；其他 → 搜索"""
    arg = (arg or "").strip()
    if not arg or arg in ("list", "ls"):
        return list_sessions()
    if arg.isdigit() or arg == "latest":
        return show_session(arg)
    return search(arg)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(list_sessions())
    elif args[0] == "show":
        print(show_session(args[1] if len(args) > 1 else "latest"))
    elif args[0] == "search" and len(args) > 1:
        print(search(" ".join(args[1:])))
    else:
        print(__doc__)
