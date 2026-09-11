"""
网页抓取工具：给 Agent 用的 fetch_url
- 抓取 URL，清洗 HTML（去 script/style/导航），保留正文和链接
- 返回截断后的纯文本 + 可点击的链接列表
- Agent 多次调用即可自主导航网页
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import re
from html import unescape
from urllib.parse import urljoin, urlparse

import requests


def _clean(html: str, base: str, max_chars: int, max_links: int = 80) -> dict:
    """把原始 HTML 清洗为 {title, text, links, error}。给 fetch_url / render_url 共用。"""
    title_match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    title = unescape(title_match.group(1).strip()) if title_match else ""
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.S | re.I)
    html = re.sub(r"<nav[^>]*>.*?</nav>", "", html, flags=re.S | re.I)
    html = re.sub(r"<footer[^>]*>.*?</footer>", "", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    links = []
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        href = m.group(1).strip()
        link_text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        link_text = unescape(link_text)[:60]
        if not href or href.startswith(("javascript:", "mailto:", "#", "tel:")):
            continue
        full_url = urljoin(base, href)
        if link_text and full_url.startswith("http"):
            links.append({"text": link_text, "url": full_url})
    seen, unique = set(), []
    for l in links:
        if l["url"] not in seen:
            seen.add(l["url"]); unique.append(l)
    unique = unique[:max_links]

    text = re.sub(r"<[^>]+>", "\n", html)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[截断，原文共{}字符]".format(len(text))
    return {"title": title, "text": text, "links": unique[:80], "error": ""}


def fetch_url(url: str, max_chars: int = 8000) -> dict:
    """
    抓取一个 URL（requests），返回清洗后的文本 + 链接列表。
    返回: {"url", "title", "text", "links", "error"}
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        except requests.exceptions.SSLError:
            print(f"⚠️ SSL 证书验证失败({url})，降级跳过验证")
            resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True, verify=False)
        resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text
    except Exception as e:
        return {"url": url, "title": "", "text": "", "links": [], "error": f"抓取失败: {e}"}

    out = _clean(html, url, max_chars)
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
            capture_output=True, text=True, timeout=180)
        html = r.stdout or ""
    except Exception as e:
        return {"url": url, "title": "", "text": "", "links": [], "error": f"渲染失败: {e}"}
    if not html:
        return {"url": url, "title": "", "text": "", "links": [],
                "error": "渲染无内容（可能是无头浏览器被组策略拦截）"}
    out = _clean(html, url, max_chars, max_links=400)
    # raw_links：全量不去重限制到 2000 条，供收录器从名单页提取教师详情链接
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
            seen.add(l["url"]); uniq.append(l)
    out["raw_links"] = uniq[:800]
    out["url"] = url
    return out


def save_faculty(site_name: str, school: str, faculty: list, note: str = "") -> dict:
    """
    Agent 提取出教师列表后调此函数存储
    faculty: [{"name": "张三", "url": "个人主页URL", "title": "教授"}, ...]
    """
    from pathlib import Path
    import json

    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / "data"
    out = DATA_DIR / f"faculty_list_{site_name}.json"

    data = {
        "site": site_name,
        "school": school,
        "note": note,
        "count": len(faculty),
        "faculty": faculty,
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": str(out), "count": len(faculty), "site": site_name}


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
