"""
网页抓取工具：给 Agent 用的 fetch_url
- 抓取 URL，清洗 HTML（去 script/style/导航），保留正文和链接
- 返回截断后的纯文本 + 可点击的链接列表
- Agent 多次调用即可自主导航网页

抓取与清洗统一走 fetch_common（UA/超时/SSL 降级/编码修正/清洗规则全项目一份）；
本模块只保留"给 Agent 的返回形状"与"无头浏览器渲染"两件特有的事。
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import re
from urllib.parse import urljoin, urlparse

from fetch_common import clean, get


def fetch_url(url: str, max_chars: int = 8000) -> dict:
    """
    抓取一个 URL（requests），返回清洗后的文本 + 链接列表。
    返回: {"url", "title", "text", "links", "error"}
    """
    try:
        resp = get(url, timeout=15)
        html = resp.text
    except Exception as e:
        return {"url": url, "title": "", "text": "", "links": [], "error": f"抓取失败: {e}"}

    out = clean(html, url, max_chars)
    out["url"] = url
    return out


# 检测可用作 JS 渲染的无头浏览器（Windows 常见路径 + 环境变量）
def _find_browser() -> str:
    import os
    from pathlib import Path
    cand = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        os.environ.get("CHROME_PATH", ""),
    ]
    for c in cand:
        if c and Path(c).exists():
            return c
    return ""


def render_url(url: str, max_chars: int = 12000, budget_ms: int = 30000) -> dict:
    """
    JS 动态页兜底：用无头浏览器（Chrome/Edge）渲染后再抓文本+链接。
    适合官网名单是 XHR/异步加载的场景（复旦/浙大/西湖等）。
    返回与 fetch_url 同构，另加 raw_links（全量链接，供收录用）。
    """
    exe = _find_browser()
    if not exe:
        return {"url": url, "title": "", "text": "", "links": [],
                "error": "找不到 Chrome/Edge 无头浏览器，请安装或设置 CHROME_PATH"}
    import subprocess
    try:
        r = subprocess.run(
            [exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--dump-dom",
             f"--virtual-time-budget={budget_ms}", "--run-all-compositor-stages-before-draw",
             "--ignore-certificate-errors",
             url],
            capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="replace")
        html = r.stdout or ""
    except Exception as e:
        return {"url": url, "title": "", "text": "", "links": [], "error": f"渲染失败: {e}"}
    if not html:
        return {"url": url, "title": "", "text": "", "links": [],
                "error": "渲染无内容（可能是无头浏览器被组策略拦截）"}
    out = clean(html, url, max_chars, max_links=400)
    # raw_links：全量不去重限制到 800 条，供收录器从名单页提取教师详情链接
    raw = []
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        href = m.group(1).strip()
        txt = re.sub(r"<[^>]+>", "", m.group(2)).strip()[:60]
        if not href or href.startswith(("javascript:", "mailto:", "#", "tel:")):
            continue
        fu = urljoin(url, href)
        if txt and fu.startswith("http"):
            raw.append({"text": txt, "url": fu})
    seen, uniq = set(), []
    for l in raw:
        if l["url"] not in seen:
            seen.add(l["url"])
            uniq.append(l)
    out["raw_links"] = uniq[:800]
    out["url"] = url
    return out


def render_site(url: str, max_pages: int = 7, budget_ms: int = 25000,
                per_page_chars: int = 6000) -> dict:
    """
    多页抓取：渲染首页 → 发现站内子页面 → 逐页渲染 → 聚合全文。
    专治 SPA/JS 站点（如实验室网站）：内容分布在 /research /people /join 等子路由里。
    返回 {"url", "pages": [{"url","title","text"}], "text": "聚合全文", "error"}
    """
    home = render_url(url, max_chars=per_page_chars, budget_ms=budget_ms)
    if home.get("error"):
        return {"url": url, "pages": [], "text": "", "error": home["error"]}

    host = urlparse(url).netloc
    # 关键词排序：实验室站点最相关的页面优先
    KEY = ("research", "people", "member", "team", "publication", "paper",
           "join", "recruit", "position", "news", "lab", "about")

    def score(u: str) -> int:
        p = urlparse(u).path.lower().strip("/")
        if not p:
            return 99
        for i, k in enumerate(KEY):
            if k in p:
                return i
        return 50

    # 收集同域子页链接（跳过锚点/文件/明显无关）
    cand = {}
    for l in home.get("raw_links", []) + home.get("links", []):
        u = l["url"].split("#")[0].rstrip("/")
        if urlparse(u).netloc != host:
            continue
        if u == url.rstrip("/"):
            continue
        if any(u.lower().endswith(ext) for ext in
               (".pdf", ".jpg", ".png", ".gif", ".zip", ".mp4", ".doc", ".docx")):
            continue
        cand[u] = l.get("text", "")

    ordered = sorted(cand, key=score)[:max_pages - 1]

    pages = [{"url": url, "title": home.get("title", ""), "text": home.get("text", "")}]
    seen_text = home.get("text", "")
    for u in ordered:
        r = render_url(u, max_chars=per_page_chars, budget_ms=budget_ms)
        if r.get("error") or not r.get("text"):
            continue
        t = r["text"]
        # 去重：子页与首页/其他页高度重复时跳过
        if t[:200] and t[:200] in seen_text:
            continue
        pages.append({"url": u, "title": r.get("title", ""), "text": t})
        seen_text += "\n" + t[:500]

    agg = "\n\n".join(f"【页面{i+1}】{p['url']}\n{p['text']}"
                      for i, p in enumerate(pages))
    return {"url": url, "pages": pages, "text": agg, "error": ""}


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://cs.pku.edu.cn"
    r = fetch_url(url)
    print(f"URL: {r['url']}")
    print(f"标题: {r['title']}")
    print(f"正文前500字:\n{r['text'][:500]}")
    print(f"\n链接({len(r['links'])}条):")
    for l in r["links"][:20]:
        print(f"  {l['text'][:30]:<30} → {l['url'][:80]}")
