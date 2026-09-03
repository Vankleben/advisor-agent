"""
工具六：论文检索与全文获取 v2（arXiv）
用法：python tools/paper_tools.py search "Yinpeng Dong"   # 查某老师近期论文
      python tools/paper_tools.py fetch 3                 # 用搜索结果的序号下载
      python tools/paper_tools.py fetch 2603.02798v1      # 或直接用 arXiv id
注意：作者名用英文（拼音）。⭐ = 目标作者是末位作者（CS 领域通常是导师主导的工作）。
"""
import json
import re
import sys
import time
import requests
import pymupdf
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PAPERS_DIR = BASE_DIR / "data" / "papers"
PAPERS_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
NS = {"a": "http://www.w3.org/2005/Atom"}


def search_papers(author_en: str, max_results: int = 15) -> list[dict]:
    """按作者英文名检索 arXiv 近期论文（按提交时间倒序）。"""
    params = {"search_query": f'au:"{author_en}"',
              "sortBy": "submittedDate", "sortOrder": "descending",
              "max_results": max_results}
    r = requests.get("http://export.arxiv.org/api/query",
                     params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()

    papers = []
    key = author_en.lower().replace(" ", "")
    for e in ET.fromstring(r.text).findall("a:entry", NS):
        authors = [a.find("a:name", NS).text for a in e.findall("a:author", NS)]
        # arXiv 作者检索是模糊匹配，必须确认目标作者真的在作者列表里
        pos = next((i for i, a in enumerate(authors)
                    if key in a.lower().replace(" ", "")), None)
        if pos is None:
            continue
        papers.append({
            "arxiv_id": e.find("a:id", NS).text.split("/abs/")[-1],
            "title": " ".join(e.find("a:title", NS).text.split()),
            "published": e.find("a:published", NS).text[:10],
            "authors": authors,
            "author_position": f"{pos + 1}/{len(authors)}",
            "is_last_author": pos == len(authors) - 1 and len(authors) > 1,
            "abstract": " ".join(e.find("a:summary", NS).text.split()),
        })
    return papers


def resolve_arxiv_id(arg: str) -> str:
    """支持两种输入：arXiv id 直接返回；纯数字视为最近一次搜索结果的序号。"""
    if re.fullmatch(r"\d{1,3}", arg):
        searches = sorted(PAPERS_DIR.glob("search_*.json"),
                          key=lambda f: f.stat().st_mtime)
        if not searches:
            raise SystemExit("还没有搜索记录，请先运行 search")
        papers = json.loads(searches[-1].read_text(encoding="utf-8"))
        idx = int(arg)
        if not (0 <= idx < len(papers)):
            raise SystemExit(f"序号 {idx} 超出范围（共 {len(papers)} 篇）")
        chosen = papers[idx]
        print(f"序号 [{idx}] → {chosen['title']}")
        return chosen["arxiv_id"]
    return arg


def fetch_paper(arxiv_id: str) -> tuple:
    """下载 PDF 并提取全文文本。带缓存（下过不重下）和重试。"""
    txt_file = PAPERS_DIR / f"{arxiv_id.replace('/', '_')}.txt"
    if txt_file.exists():
        print(f"缓存命中，直接读取：{txt_file.name}")
        return txt_file, None, len(txt_file.read_text(encoding="utf-8"))

    url = f"https://arxiv.org/pdf/{arxiv_id}"
    for attempt in range(3):
        try:
            print("下载中（arxiv 服务器较慢，耐心等待）...")
            r = requests.get(url, headers=HEADERS, timeout=120)
            r.raise_for_status()
            break
        except requests.RequestException as e:
            print(f"第 {attempt + 1} 次下载失败：{type(e).__name__}，5 秒后重试")
            time.sleep(5)
    else:
        raise RuntimeError("三次下载均失败，换个时间再试")

    doc = pymupdf.open(stream=r.content, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    txt_file.write_text(text, encoding="utf-8")
    return txt_file, len(doc), len(text)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    cmd, arg = sys.argv[1], sys.argv[2]

    if cmd == "search":
        papers = search_papers(arg)
        out = PAPERS_DIR / f"search_{arg.replace(' ', '_')}.json"
        out.write_text(json.dumps(papers, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"找到 {len(papers)} 篇（⭐=末位作者，通常是他主导的论文）：\n")
        for i, p in enumerate(papers):
            star = "⭐" if p["is_last_author"] else "  "
            print(f"[{i}]{star}{p['published']} | {p['title']}")
            print(f"      作者位置 {p['author_position']} | id: {p['arxiv_id']}")
        print(f"\n结果已存：{out}")
        print("提示：位置靠中后且总人数很多的（如 31/37）是大型合作的挂名，"
              "⭐末位作者的才是他主导的论文，优先读这些")

    elif cmd == "fetch":
        arxiv_id = resolve_arxiv_id(arg)
        txt_file, pages, chars = fetch_paper(arxiv_id)
        print(f"提取完成：{pages} 页，{chars} 字符 → {txt_file}")

    else:
        print(f"未知命令 {cmd}，支持 search / fetch")


if __name__ == "__main__":
    main()