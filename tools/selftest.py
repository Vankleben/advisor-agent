"""离线自检：确认共享基础设施与关键契约没有回归。

特点：不起外部网络请求、不调 LLM、不改动 data/ 与 archive/ 下的任何数据文件，
所以随时可以跑：python tools/selftest.py

覆盖的历史问题：
- P0：全新克隆（无 archive/）时 analyze_paper 曾在模块级读 profile.json，导致连 main 都启动不了
- P1：monitor 简报的 GitHub 标记写"新仓库/新动态"、判定却查"新仓库/新推送"，GitHub 更新永不计数
- 重复实现：模型表 11 份、UA 4 种、归一化 6 处、抓取 6 套 —— 现在必须只剩一份
"""
import ast
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "tools"))

RESULTS = []
_SAMPLE_HTML = """<html><head><title>样例页</title>
<script>var secret=1;</script><style>.a{}</style></head>
<body><nav>导航区</nav><h1>导师名单</h1>
<div class="box"><a href="/p/1.htm">甲老师</a><a href="https://out.example/a">乙老师</a></div>
<footer>版权所有</footer></body></html>"""


def check(name):
    """装饰器：登记一个检查项。"""
    def deco(fn):
        RESULTS.append((name, fn))
        return fn
    return deco


# ---------------- 本地 HTTP 服务（供抓取层检查） ----------------

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/gbk"):
            body = ("<html><head><title>中文页</title></head><body><p>" +
                    "".join(f"第{i}段：足够的正文长度用于编码探测。" for i in range(30)) +
                    "</p></body></html>").encode("gbk")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/page"):
            body = _SAMPLE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


def _serve():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


# ---------------- 检查项 ----------------

@check("所有工具模块可导入")
def _imports():
    import importlib
    mods = ["llm_client", "text_norm", "fetch_common", "store", "user_profile", "memory",
            "chat_history", "knowledge_store", "paper_tools", "analyze_paper",
            "critique_thinking", "advisor_deepdive", "path_analysis", "compare_advisors",
            "web_fetch", "monitor", "monitor_daily", "llm_card", "batch_cards",
            "crawl_faculty", "enrich_faculty", "universal_crawl", "add_career_note"]
    for m in mods:
        importlib.import_module(m)
    return f"{len(mods)} 个模块全部导入成功"


@check("模型表只剩一份（llm_client）")
def _single_model_table():
    offenders = []
    for f in list(BASE_DIR.glob("*.py")) + list(BASE_DIR.glob("tools/*.py")):
        # 本文件含检测用的字符串常量，跳过自身
        if f.name in ("llm_client.py", "config.py", "config.example.py", "selftest.py"):
            continue
        if "moonshot-v1" in f.read_text(encoding="utf-8"):
            offenders.append(f.name)
    assert not offenders, f"仍有模型表副本：{offenders}"
    return "无副本（只有 llm_client 定义模型名）"


@check("抓取/归一化实现只剩一份")
def _single_helpers():
    bad = []
    for f in BASE_DIR.glob("tools/*.py"):
        # 本文件含检测用的字符串常量，跳过自身
        if f.name in ("fetch_common.py", "text_norm.py", "selftest.py"):
            continue
        s = f.read_text(encoding="utf-8")
        if "Mozilla/5.0" in s:
            bad.append(f"{f.name}:UA")
        if "0-9a-zA-Z一-鿿" in s:
            bad.append(f"{f.name}:归一化")
    assert not bad, f"仍有重复实现：{bad}"
    return "无重复（UA 只在 fetch_common、归一化只在 text_norm）"


@check("text_norm 归一化行为")
def _text_norm():
    from text_norm import flat, loose
    assert flat("a b\nc") == "abc"
    assert loose("Re-bound\nForce") == loose("Rebound Force") == "reboundforce"
    assert loose("注意力（机制）") == "注意力机制"
    assert loose(None) == "" and flat(None) == ""
    return "折行连字符/中文标点/空值均按预期归一化"


@check("fetch_common 抓取层行为")
def _fetch_common():
    import fetch_common as fc
    srv, base = _serve()
    try:
        r = fc.get(f"{base}/page", timeout=5)
        assert "导师名单" in r.text
        page = fc.clean(r.text, base + "/page", 8000)
        assert page["title"] == "样例页"
        assert [l["text"] for l in page["links"]] == ["甲老师", "乙老师"]
        assert "var secret" not in page["text"] and "导航区" not in page["text"]
        gbk = fc.get(f"{base}/gbk", timeout=5)
        assert "编码探测" in gbk.text, "GBK 页编码修正失败"
        try:
            fc.get(f"{base}/missing", timeout=5)
            raise AssertionError("404 未抛错")
        except Exception as e:
            assert type(e).__name__ == "HTTPError", f"404 抛出了 {type(e).__name__}"
        t = fc.strip_html(_SAMPLE_HTML)
        assert "导师名单" in t and "版权所有" not in t and "var secret" not in t
        return "编码修正/404 抛错/清洗去噪/链接提取均正常"
    finally:
        srv.shutdown()


@check("fetch_common curl 兜底可用")
def _curl_transport():
    import fetch_common as fc
    assert fc._curl_exe(), "未找到 curl，TLS 指纹被拦的站点将无法兜底"
    srv, base = _serve()
    try:
        r = fc.get(f"{base}/page", timeout=8, transport="curl")
        assert r.status_code == 200 and "导师名单" in r.text
        assert callable(r.json) and r.apparent_encoding
        try:
            fc.get(f"{base}/missing", timeout=8, transport="curl")
            raise AssertionError("curl 通道的 404 未抛错")
        except Exception as e:
            assert type(e).__name__ == "HTTPError", f"抛出了 {type(e).__name__}"
        return "curl 通道可取页面、能正确抛 404（供 TLS 指纹被拦的站点兜底）"
    finally:
        srv.shutdown()


@check("注解引用的名字都有定义（版本无关）")
def _annotation_names():
    """捕获"删了 import 却留着类型注解"这类错误。

    Python 3.14 起注解延迟求值（PEP 649），本机装 3.14 时这类错误在运行期不报错，
    但项目实际跑在 conda 环境的 3.11 上，注解会立即求值并抛 NameError。
    这里做与解释器版本无关的静态检查，避免验证环境与运行环境不一致时漏掉。
    """
    import builtins
    import ast as _ast

    known = set(dir(builtins)) | {"self", "cls"}
    problems = []
    files = sorted(BASE_DIR.glob("tools/*.py")) + [BASE_DIR / "main.py", BASE_DIR / "web_server.py"]

    for f in files:
        tree = _ast.parse(f.read_text(encoding="utf-8"))
        bound = set(known)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                bound |= {(a.asname or a.name.split(".")[0]) for a in node.names}
            elif isinstance(node, _ast.ImportFrom):
                bound |= {(a.asname or a.name) for a in node.names}
            elif isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                bound.add(node.name)
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    args = (list(node.args.posonlyargs) + list(node.args.args)
                            + list(node.args.kwonlyargs))
                    for a in args:
                        bound.add(a.arg)
                    if node.args.vararg:
                        bound.add(node.args.vararg.arg)
                    if node.args.kwarg:
                        bound.add(node.args.kwarg.arg)
            elif isinstance(node, _ast.Name) and isinstance(node.ctx, _ast.Store):
                bound.add(node.id)

        for node in _ast.walk(tree):
            anns = []
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                anns = [a.annotation for a in (list(node.args.posonlyargs) + list(node.args.args)
                                               + list(node.args.kwonlyargs))
                        if a.annotation is not None]
                if node.args.vararg and node.args.vararg.annotation:
                    anns.append(node.args.vararg.annotation)
                if node.args.kwarg and node.args.kwarg.annotation:
                    anns.append(node.args.kwarg.annotation)
                if node.returns is not None:
                    anns.append(node.returns)
            elif isinstance(node, _ast.AnnAssign) and node.annotation is not None:
                anns = [node.annotation]
            for a in anns:
                for sub in _ast.walk(a):
                    if isinstance(sub, _ast.Name) and sub.id not in bound:
                        problems.append(f"{f.name}:{sub.lineno} 注解引用了未定义的名字 {sub.id!r}")

    assert not problems, "；".join(problems[:4])
    return f"{len(files)} 个文件里注解引用的名字均有定义"


@check("store 本地读取接口")
def _store():
    import store
    cards = list(store.iter_cards())
    assert cards and all(isinstance(s, str) for s, _ in cards)
    name = cards[0][1]["name"]
    assert store.find_card(name) is not None
    assert store.find_card("此人不存在_自检") is None
    assert isinstance(store.has_deepdive(name), bool)
    return f"卡片 {len(cards)} 条 / {len({s for s, _ in cards})} 个站点，按名检索正常"


@check("monitor 简报前缀契约（P1 回归）")
def _monitor_contract():
    import monitor as mon
    entry = {"changes": [f"{mon.SRC_NEW_PREFIX} http://x", "  · 新增"],
             "arxiv": [{"id": "1"}], "github": [f"{mon.GH_NEW_PREFIX}: a/b（最近更新 x）"]}
    assert mon.count_new(entry) == (1, 1, 1), f"count_new 结果异常：{mon.count_new(entry)}"
    assert mon.has_real_changes({"per_teacher": [entry]}) == (3, 1)
    quiet = {"per_teacher": [{"changes": ["[无变化] u"], "arxiv": [], "github": []}]}
    assert mon.has_real_changes(quiet) == (0, 0)
    assert mon.scan.__doc__ and "情报简报" in mon.scan.__doc__
    return "主页/论文/GitHub 三类新增都能计数，无变化时正确归零"


@check("main 工具表与派发表一一对应")
def _registry():
    import main as m
    names = [t["function"]["name"] for t in m.TOOLS]
    assert len(names) == len(set(names))
    assert set(names) == set(m.DISPATCH), set(names) ^ set(m.DISPATCH)
    for n in names:
        assert callable(m.DISPATCH[n]), n
    return f"{len(names)} 个工具，TOOLS 与 DISPATCH 完全一致且均可调用"


@check("画像缺失时不再崩（P0 回归）")
def _fresh_clone():
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "tools").mkdir()
        for f in (BASE_DIR / "tools").glob("*.py"):
            shutil.copy(f, tmp / "tools" / f.name)
        for f in ("config.py",):
            if (BASE_DIR / f).exists():
                shutil.copy(BASE_DIR / f, tmp / f)
        code = ("import sys; sys.path.insert(0, 'tools');"
                "import analyze_paper as ap;"
                "print('OK', '画像缺失' in ap.profile_block())")
        r = subprocess.run([sys.executable, "-c", code], cwd=str(tmp),
                           capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="replace")
        assert r.returncode == 0, (r.stdout + r.stderr)[-400:]
        assert "OK True" in r.stdout, r.stdout
        return "无 data/archive、无 profile.json 时仍能导入并优雅降级"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------- 跑全部检查 ----------------

def main() -> int:
    # 数据文件只读校验：自检不得改动用户数据
    watch = [p for d in ("data", "archive") for p in (BASE_DIR / d).rglob("*") if p.is_file()]
    before = {str(p): p.stat().st_mtime for p in watch}

    ok = failed = 0
    for name, fn in RESULTS:
        try:
            detail = fn()
            ok += 1
            print(f"  ✅ {name}：{detail}")
        except Exception as e:
            failed += 1
            print(f"  ❌ {name}：{type(e).__name__}: {e}")

    after = {str(p): p.stat().st_mtime for p in watch if p.exists()}
    changed = [p for p in after if before.get(p) != after[p]] + \
              [p for p in before if p not in after]
    if changed:
        failed += 1
        print(f"  ❌ 自检改动了数据文件（不应发生）：{[Path(c).name for c in changed[:5]]}")
    else:
        print(f"  ✅ 未改动任何数据文件（监视 {len(before)} 个）")

    print(f"\n通过 {ok} 项，失败 {failed} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    print("=== 离线自检（不联网/不调 LLM/不改数据）===")
    sys.exit(main())
