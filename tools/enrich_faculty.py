"""
工具二：详情页追踪器 v2.2
输入：data/faculty_{site}.json（模块一/五产物）
输出：data/faculty_{site}_enriched.json
用法：python tools/enrich_faculty.py collegeai
      python tools/enrich_faculty.py life
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import re
import sys
import time
import requests
from bs4 import BeautifulSoup
from html import unescape
from urllib.parse import urlparse
from datetime import date
from pathlib import Path

from fetch_common import get

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

CONTENT_SELECTORS = {
    "collegeai.tsinghua.edu.cn": [".con", ".v_news_content", ".box0"],
    "life.tsinghua.edu.cn": ["#vsb_content"],
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


# ---- 站点专用抽取器：整站 JS 渲染、但内容已内嵌在页面脚本字段里的站点 ----
# 西湖大学教师主页：页面无正文、无外链，服务端把各栏目写进 JS 字符串字段
# （post 所属学院 / subject 研究方向 / lab 实验室 / biographyStr 简介 /
#   historyStr 教育与工作经历 / researchStr 学术成果及研究方向 / content 详情正文）。
# 抽取这些字段即可，无需无头浏览器渲染。
# 注意 keywords / brief / phone / title 等字段在本站是页头页尾的 UI 文案（如 "Support Us"），
# 不是教师信息，不能收。

WESTLAKE_FIELDS = (("post", "所属学院"), ("subject", "研究方向"), ("lab", "实验室"),
                   ("biographyStr", "个人简介"), ("historyStr", "教育与工作经历"),
                   ("researchStr", "学术成果及研究方向"))

_JS_STR_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*"((?:[^"\\]|\\.)*)"')


def _js_unescape(text: str) -> str:
    """还原 JS 字符串转义（\\/ \\" \\n \\uXXXX 等）。"""
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    for a, b in (("\\/", "/"), ('\\"', '"'), ("\\n", "\n"), ("\\r", ""),
                 ("\\t", " "), ("\\'", "'")):
        text = text.replace(a, b)
    return text


def _html_fragment_to_text(fragment: str) -> str:
    return BeautifulSoup(_js_unescape(fragment), "lxml").get_text("\n", strip=True)


def parse_westlake_detail(html: str, page_url: str) -> dict:
    """西湖大学教师主页：按内嵌字段抽取正文（返回结构与 parse_detail 一致）。"""
    parts = []
    for key, label in WESTLAKE_FIELDS:
        for m in _JS_STR_RE.finditer(html):
            if m.group(1) == key:
                val = m.group(2)
                if val.strip():
                    parts.append(f"【{label}】{_html_fragment_to_text(val)}")
                break
    # content 字段会有多段（研究介绍、代表论文等），全部保留
    for i, m in enumerate((m for m in _JS_STR_RE.finditer(html) if m.group(1) == "content"), 1):
        val = m.group(2)
        if len(val) > 100:
            parts.append(f"【详情内容{i}】{_html_fragment_to_text(val)}")

    text = "\n".join(p for p in parts if p.strip())
    emails = list(dict.fromkeys(EMAIL_RE.findall(text)))
    return {"detail_text": text[:3000], "emails": emails,
            "external_links": [], "fallback": True}


def _is_westlake_profile(page_url: str) -> bool:
    u = urlparse(page_url)
    return "westlake.edu.cn" in u.netloc and "/faculty/" in u.path


def parse_detail(html: str, page_url: str) -> dict:
    if _is_westlake_profile(page_url):
        return parse_westlake_detail(html, page_url)
    soup = BeautifulSoup(html, "lxml")
    domain = urlparse(page_url).netloc
    selectors = CONTENT_SELECTORS.get(domain)

    if selectors:
        parts = []
        for sel in selectors:
            for el in soup.select(sel):
                t = el.get_text(" ", strip=True)
                if t and t not in parts:
                    parts.append(t)
        text = "\n".join(parts)
        fallback = False
    else:
        text = soup.get_text(" ", strip=True)
        fallback = True

    emails = list(dict.fromkeys(EMAIL_RE.findall(text)))
    external = []
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if h.startswith("http") and urlparse(h).netloc != domain and "tsinghua.edu.cn" not in h:
            pair = {"url": h, "label": a.get_text(strip=True)}
            if pair not in external:
                external.append(pair)

    return {"detail_text": text[:3000], "emails": emails,
            "external_links": external[:10], "fallback": fallback}


def main():
    site = sys.argv[1] if len(sys.argv) > 1 else "collegeai"
    in_file = DATA_DIR / f"faculty_{site}.json"
    out_file = DATA_DIR / f"faculty_{site}_enriched.json"

    if not in_file.exists():
        print(f"找不到输入文件 {in_file}，请先运行名单抓取")
        return

    with open(in_file, encoding="utf-8") as f:
        data = json.load(f)

    done = {}
    if out_file.exists():
        with open(out_file, encoding="utf-8") as f:
            for t in json.load(f)["teachers"]:
                if t.get("detail") and not t["detail"].get("error"):
                    done[t["name"]] = t
        print(f"续传：已有 {len(done)} 条成功记录，跳过")

    teachers = []
    total = len(data["teachers"])
    for i, t in enumerate(data["teachers"]):
        if t["name"] in done:
            teachers.append(done[t["name"]])
            continue

        url = t.get("detail_url")
        if not url or url.startswith("javascript:"):
            t["detail"] = {"no_detail_page": True}
        else:
            url = re.sub(r"<.*$", "", url).strip()
            t["detail_url"] = url
            try:
                resp = get(url, timeout=15)
                t["detail"] = parse_detail(resp.text, url)
                if not t.get("email") and t["detail"]["emails"]:
                    t["email"] = t["detail"]["emails"][0]
            except requests.RequestException as e:
                t["detail"] = {"error": str(e)}
        teachers.append(t)

        if (i + 1) % 10 == 0:
            print(f"进度 {i + 1}/{total}")
        time.sleep(0.5)

    output = {
        "source_url": data["source_url"],
        "crawl_date": data["crawl_date"],
        "enrich_date": date.today().isoformat(),
        "count": len(teachers),
        "teachers": teachers,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    ok = sum(1 for t in teachers if t.get("detail")
             and not t["detail"].get("error") and not t["detail"].get("no_detail_page"))
    fb = sum(1 for t in teachers if t.get("detail") and t["detail"].get("fallback"))
    nod = sum(1 for t in teachers if t.get("detail") and t["detail"].get("no_detail_page"))
    err = sum(1 for t in teachers if t.get("detail") and t["detail"].get("error"))
    print(f"完成：{ok}/{total} 成功（其中 {fb} 条外链降级），{nod} 条无详情页，{err} 条失败 → {out_file}")


if __name__ == "__main__":
    main()