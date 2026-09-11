"""
工具六：论文检索与全文获取 v2（arXiv）
用法：python tools/paper_tools.py search "Yinpeng Dong"   # 查某老师近期论文
      python tools/paper_tools.py fetch 3                 # 用搜索结果的序号下载
      python tools/paper_tools.py fetch 2603.02798v1      # 或直接用 arXiv id
注意：作者名用英文（拼音）。⭐ = 目标作者是末位作者（CS 领域通常是导师主导的工作）。
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


def search_europepmc(author_en: str, affiliation: str = "", max_results: int = 15) -> list[dict]:
    """
    按作者英文名检索 Europe PMC（覆盖 PubMed + 预印本，即 Cell/Nature/... 等生物医学期刊）。
    适配 arXiv 检索不到的方向（生命科学/医学）。

    同名去歧义：给了 affiliation（如 "Tsinghua"）时按机构过滤，能过滤掉绝大多数同名学者。
    作者检索是模糊匹配，逐个确认目标作者真的在作者列表里；末位作者标记沿用 arXiv 侧语义。
    """
    query = f'AUTH:"{author_en}"'
    if affiliation:
        query += f' AND AFF:"{affiliation}"'
    params = {"query": query, "format": "json", "pageSize": max_results,
              "sort": "P_PDATE_D desc", "resultType": "core"}
    r = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                     params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()

    papers = []
    # Europe PMC 返回的作者名多为 "Shen X"（姓 + 名缩写）或全名，需兼容两种格式匹配
    parts = author_en.split()
    last = parts[-1].lower()          # Xiaohua Shen -> shen
    first_init = parts[0][0].lower() if parts else ""   # -> x

    def _match(a: str) -> bool:
        al = a.lower().replace("-", " ").strip()
        if author_en.lower().replace("-", " ") in al:      # 全名直接命中
            return True
        toks = al.split()
        if not toks:
            return False
        # "shen x" / "shen, x" 形式：姓在末位 token 或首 token
        if last in toks[0] and len(toks) >= 2 and toks[1].startswith(first_init):
            return True
        if last in toks[-1] and len(toks) >= 2 and toks[0].startswith(first_init):
            return True
        return False

    for it in r.json().get("resultList", {}).get("result", []):
        auth_list = ((it.get("authorList") or {}).get("author") or [])
        authors = [a.get("fullName") or a.get("lastName", "") for a in auth_list]
        pos = next((i for i, a in enumerate(authors) if _match(a)), None)
        if pos is None:
            continue
        jinfo = (it.get("journalInfo") or {}).get("journal") or {}
        papers.append({
            "source": "europepmc",
            "pmid": it.get("pmid", ""),
            "doi": it.get("doi", ""),
            "title": (it.get("title") or "").rstrip("."),
            "journal": jinfo.get("title") or it.get("bookOrReportDetails", {}).get("publisher", ""),
            "published": str(it.get("pubYear") or ""),
            "authors": authors,
            "author_position": f"{pos + 1}/{len(authors)}" if authors else "",
            "is_last_author": bool(authors) and pos == len(authors) - 1 and len(authors) > 1,
            "url": (f"https://pubmed.ncbi.nlm.nih.gov/{it['pmid']}/" if it.get("pmid")
                    else f"https://doi.org/{it.get('doi', '')}"),
            "abstract": " ".join((it.get("abstractText") or "").split())[:800],
        })
    return papers


def fetch_lab_publications(lab_url: str, max_papers: int = 30) -> list[dict]:
    """
    从实验室官网的 Publications 页提取论文列表（PI 自己维护，是最权威的成果列表）。
    兜底场景：arXiv/Europe PMC 都查不到时用这个（如 CS 之外的冷门方向、新组、中文站点）。

    支持的页面形态：SPA（React/Vue，需渲染）与静态页；返回 [{title, authors, venue, year, url}]。
    """
    import sys as _s
    from pathlib import Path as _P
    _s.path.insert(0, str(_P(__file__).resolve().parent))
    from web_fetch import render_site, render_url

    # 1. 定位 publications 页：优先在站点里找，找不到就把传入 URL 当 publications 页
    page_url = lab_url
    low = lab_url.lower()
    if not any(k in low for k in ("publication", "paper", "achievement", "成果", "论文")):
        try:
            site = render_site(lab_url, max_pages=8)
            for p in site.get("pages", []):
                pl = p["url"].lower()
                if any(k in pl for k in ("publication", "paper")):
                    page_url = p["url"]
                    break
        except Exception:
            pass

    # 2. 抓页面正文（先普通抓，内容太少就渲染）
    text = ""
    try:
        r = render_url(page_url, max_chars=25000, budget_ms=30000)
        if not r.get("error"):
            text = r["text"]
    except Exception as e:
        return [{"error": f"抓取失败：{e}"}]
    if not text:
        return [{"error": f"未获取到内容：{page_url}"}]

    # 3. 交给 LLM 抽取结构化论文条目
    import sys as _sys2
    D = _P(__file__).resolve().parent.parent
    _sys2.path.insert(0, str(D))
    from config import PROVIDER, API_KEY
    from openai import OpenAI
    from web_fetch import _find_browser  # noqa

    PROVIDERS = {"moonshot": ("https://api.moonshot.cn/v1", "moonshot-v1-32k"),
                 "deepseek": ("https://api.deepseek.com", "deepseek-chat")}
    base_url, model = PROVIDERS[PROVIDER]
    client = OpenAI(api_key=API_KEY, base_url=base_url)

    prompt = (
        "从下面这个实验室官网的论文页面正文中，提取所有论文条目。\n"
        "严格规则：只提取原文中真实出现的论文，禁止补充你知道的其他论文；"
        "找不到的字段填 null。\n\n"
        f"输出 JSON：{{\"papers\": [{{\"title\": \"标题\", \"authors\": \"作者串\", "
        f"\"venue\": \"期刊/会议\", \"year\": \"年份\", \"url\": \"链接或null\"}}]}}\n\n"
        f"正文：\n{text[:20000]}"
    )
    resp = client.chat.completions.create(
        model=model, temperature=0.1,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}])
    papers = json.loads(resp.choices[0].message.content).get("papers", [])

    # 4. 反幻觉：标题必须能在原文中找到（归一化比对，免疫空格/连字符差异）
    norm = lambda s: re.sub(r"[^0-9a-zA-Z一-鿿]+", "", str(s or "")).lower()
    flat = norm(text)
    ok = []
    for p in papers[:max_papers]:
        if p.get("title") and norm(p["title"])[:60] in flat:
            p["source"] = "lab_publications"
            p["page"] = page_url
            ok.append(p)
    return ok


def merge_paper_sources(arxiv: list, epmc: list, lab: list) -> list[dict]:
    """
    跨源合并去重：同标题（归一化比对）的论文合并为一条，sources 字段记录命中来源。
    价值：官网论文可补上 arXiv/PMC 缺失的条目，多源命中则互相印证，可信度更高。
    """
    norm = lambda s: re.sub(r"[^0-9a-zA-Z一-鿿]+", "", str(s or "")).lower()[:70]
    merged: dict[str, dict] = {}

    def add(p: dict, src: str):
        key = norm(p.get("title"))
        if not key:
            return
        if key in merged:
            m = merged[key]
            if src not in m["sources"]:
                m["sources"].append(src)
            # 用更完整的信息补齐空缺字段（官网常有作者全名/期刊/年份）
            for f in ("authors", "journal", "venue", "published", "year", "url", "abstract"):
                if not m.get(f) and p.get(f):
                    m[f] = p[f]
            if p.get("is_last_author"):
                m["is_last_author"] = True
        else:
            m = dict(p)
            m["sources"] = [src]
            merged[key] = m

    for p in arxiv:
        add(p, "arXiv")
    for p in epmc:
        add(p, "EuropePMC")
    for p in lab:
        add(p, "实验室官网")
    return list(merged.values())


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