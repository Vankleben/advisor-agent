"""
网页抓取工具：给 Agent 用的 fetch_url
- 抓取 URL，清洗 HTML（去 script/style/导航），保留正文和链接
- 返回截断后的纯文本 + 可点击的链接列表
- Agent 多次调用即可自主导航网页
"""
import re
from html import unescape
from urllib.parse import urljoin, urlparse

import requests


def fetch_url(url: str, max_chars: int = 8000) -> dict:
    """
    抓取一个 URL，返回清洗后的文本 + 链接列表
    返回: {"url": url, "title": "", "text": "正文(截断)", "links": [{"text":"链接文字", "url":"完整URL"}], "error": ""}
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text
    except Exception as e:
        return {"url": url, "title": "", "text": "", "links": [], "error": f"抓取失败: {e}"}

    # 提取 title
    title_match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    title = unescape(title_match.group(1).strip()) if title_match else ""

    # 删除不需要的标签
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.S | re.I)
    html = re.sub(r"<nav[^>]*>.*?</nav>", "", html, flags=re.S | re.I)
    html = re.sub(r"<footer[^>]*>.*?</footer>", "", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    # 提取所有链接（在清洗前抓，否则丢失）
    links = []
    base = url
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        href = m.group(1).strip()
        link_text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        link_text = unescape(link_text)[:60]
        if not href or href.startswith(("javascript:", "mailto:", "#", "tel:")):
            continue
        full_url = urljoin(base, href)
        if link_text and full_url.startswith("http"):
            links.append({"text": link_text, "url": full_url})

    # 去重（按 URL）
    seen = set()
    unique_links = []
    for l in links:
        if l["url"] not in seen:
            seen.add(l["url"])
            unique_links.append(l)

    # 提取纯文本
    text = re.sub(r"<[^>]+>", "\n", html)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    text = "\n".join(lines)

    # 截断
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[截断，原文共{}字符]".format(len(text))

    return {
        "url": url,
        "title": title,
        "text": text,
        "links": unique_links[:80],  # 最多 80 条链接，避免 token 爆炸
        "error": "",
    }


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
