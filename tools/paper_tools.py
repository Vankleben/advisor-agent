"""
工具六：论文检索与全文获取 v2（arXiv）
用法：python tools/paper_tools.py search "John Smith"   # 查某老师近期论文
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

from fetch_common import UA, get
from llm_client import make_client, model_for
from text_norm import loose

BASE_DIR = Path(__file__).resolve().parent.parent
PAPERS_DIR = BASE_DIR / "data" / "papers"
PAPERS_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": UA}
NS = {"a": "http://www.w3.org/2005/Atom"}


def _get_with_retry(url: str, params: dict = None, timeout: int = 30,
                    tries: int = 3, headers: dict = None) -> requests.Response:
    """统一外部 API 请求封装：对 429 限流 / 5xx / 连接重置做退避重试（3→6→12s）。

    传输层仍走 fetch_common.get（统一 UA 与 SSL 降级），这里只叠加"学术接口限流退避"策略
    ——页面抓取不需要退避，接口调用需要，故保留这一层。
    """
    last = None
    for i in range(tries):
        try:
            r = get(url, params=params, timeout=timeout, headers=headers or HEADERS,
                    check_status=False)
            if r.status_code in (429, 500, 502, 503):
                last = requests.HTTPError(f"HTTP {r.status_code}", response=r)
                print(f"⚠️ 接口限流/异常（HTTP {r.status_code}），{2 ** (i + 1) * 3}s 后重试...")
                time.sleep(2 ** (i + 1) * 3)   # 6→12→24s
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            print(f"⚠️ 请求失败（{type(e).__name__}），{2 ** (i + 1) * 3}s 后重试...")
            time.sleep(2 ** (i + 1) * 3)
    raise RuntimeError(f"重试 {tries} 次仍失败：{last}")


def search_papers(author_en: str, max_results: int = 15) -> list[dict]:
    """按作者英文名检索 arXiv 近期论文（按提交时间倒序）。带限流退避重试。"""
    params = {"search_query": f'au:"{author_en}"',
              "sortBy": "submittedDate", "sortOrder": "descending",
              "max_results": max_results}
    # 超时放宽到 45s：export.arxiv.org 的 http 会 301 跳到 https，而该域名 https 常年偏慢
    # （实测同一台机器上 14s 成功与 >30s 超时交替出现），30s 阈值误报率偏高
    r = _get_with_retry("http://export.arxiv.org/api/query", params=params, timeout=45)

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


def search_by_seed(seed_title: str, author_name: str = "", max_results: int = 40) -> list[dict]:
    """
    种子论文策略（重名终结者）：
    用一篇已知的代表作（如深潜报告里提取的论文标题）当"种子"，反查作者，
    再按【姓名级合作者交集】过滤其全部论文——精准命中本人，滤掉同名的其他学者。

    实测：'Wei Wang' 100 篇污染列表 → 过滤后仅保留 6 篇真实 CS 论文。
    """
    UA = {"User-Agent": "advisor-agent/1.0 (mailto:advisor@example.com)"}
    # 1. 用标题找种子论文
    r = _get_with_retry("https://api.openalex.org/works",
                        params={"search": seed_title, "per-page": 5},
                        timeout=25, headers=UA)
    results = r.json().get("results", [])
    if not results:
        return [{"error": f"未找到种子论文：{seed_title}"}]
    # 选标题最匹配的一条
    # 标题/作者名归一化比对（唯一实现见 text_norm.loose；纯英文名与旧实现等价）
    norm = loose
    seed = min(results, key=lambda w: 0 if norm(seed_title)[:20] in norm(w.get("display_name")) else 1)

    # 2. 定位目标作者 + 建立合作者名单（姓名级，绕开被污染的 author id）
    seed_authors = [a for a in seed.get("authorships", []) if a.get("author", {}).get("display_name")]
    target = None
    if author_name:
        tkey = norm(author_name)
        target = next((a for a in seed_authors
                       if tkey in norm(a["author"]["display_name"])), None)
    if target is None:
        return [{"error": f"种子论文《{seed.get('display_name', '')[:50]}》作者中找不到 {author_name or '（未提供）'}",
                 "seed_authors": [a["author"]["display_name"] for a in seed_authors]}]
    co_names = {norm(a["author"]["display_name"])
                for a in seed_authors
                if a is not target and a.get("author", {}).get("display_name")}
    target_id = (target.get("author", {}).get("id") or "").split("/")[-1]
    if not target_id:
        return [{"error": "无法获取该作者的 OpenAlex 档案 ID"}]

    # 3. 拉该作者名下全部论文，用合作者姓名交集过滤
    r2 = _get_with_retry("https://api.openalex.org/works",
                         params={"filter": f"author.id:{target_id}",
                                 "per-page": 100, "sort": "publication_year:desc"},
                         timeout=30, headers=UA)
    kept, dropped = [], 0
    for w in r2.json().get("results", []):
        wnames = {norm(a["author"]["display_name"])
                  for a in w.get("authorships", []) if a.get("author", {}).get("display_name")}
        if not (names := wnames & co_names):
            dropped += 1
            continue
        venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        kept.append({
            "title": w.get("display_name", ""),
            "year": str(w.get("publication_year") or ""),
            "venue": venue,
            "doi": doi,
            "matched_coauthors": sorted(names)[:3],
            "cited_by": w.get("cited_by_count", 0),
            "source": "seed",
        })
    kept.sort(key=lambda p: (p["year"] or "0"), reverse=True)
    return kept[:max_results] if kept else [{"error": "合作者交集过滤后无结果（可能该作者在该库的档案被合并，请人工核对）"}]


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
    r = get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params=params, headers=HEADERS, timeout=30)

    papers = []
    # Europe PMC 返回的作者名多为 "Smith J"（姓 + 名缩写）或全名，需兼容两种格式匹配
    parts = author_en.split()
    last = parts[-1].lower()          # John Smith -> smith
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
            "pmcid": it.get("pmcid", ""),
            "doi": it.get("doi", ""),
            "is_oa": it.get("isOpenAccess") == "Y",
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
    text, pdf_links = "", []
    try:
        r = render_url(page_url, max_chars=25000, budget_ms=30000)
        if not r.get("error"):
            text = r["text"]
            # 收集页面里的 PDF 直链（供后续 fetch_fulltext 下载全文）
            for l in r.get("raw_links", []):
                u = l["url"]
                if u.lower().endswith(".pdf") or "pdf" in (l.get("text") or "").lower():
                    if u.lower().endswith(".pdf"):
                        pdf_links.append(u)
    except Exception as e:
        return [{"error": f"抓取失败：{e}"}]
    if not text:
        return [{"error": f"未获取到内容：{page_url}"}]

    # 3. 交给 LLM 抽取结构化论文条目
    client = make_client()

    pdf_block = "\n".join(pdf_links[:40]) if pdf_links else "（无）"
    prompt = (
        "从下面这个实验室官网的论文页面正文中，提取所有论文条目。\n"
        "严格规则：只提取正文中真实出现的论文，禁止补充你知道的其他论文；"
        "找不到的字段填 null。\n"
        "pdf 字段：若该论文在'可用PDF链接列表'中有对应 PDF（按文件名中的作者/期刊/年份/标题关键词匹配），"
        "必须原样填入该链接；无法确定对应关系时填 null，禁止编造链接。\n\n"
        f"输出 JSON：{{\"papers\": [{{\"title\": \"标题\", \"authors\": \"作者串\", "
        f"\"venue\": \"期刊/会议\", \"year\": \"年份\", \"url\": \"论文页链接或null\", "
        f"\"pdf\": \"对应PDF直链或null\"}}]}}\n\n"
        f"正文：\n{text[:18000]}\n\n"
        f"可用PDF链接列表（只能从中选择，不能编造）：\n{pdf_block}"
    )
    resp = client.chat.completions.create(
        model=model_for("mid"), temperature=0.1,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}])
    papers = json.loads(resp.choices[0].message.content).get("papers", [])

    # 4. 反幻觉：标题必须能在原文中找到（归一化比对）；pdf 链接必须在实际抓到的链接列表里
    flat = loose(text)
    valid_pdfs = set(pdf_links)
    ok = []
    for p in papers[:max_papers]:
        if p.get("title") and loose(p["title"])[:60] in flat:
            if p.get("pdf") and p["pdf"] not in valid_pdfs:
                p["pdf"] = None   # 编造的 PDF 链接直接丢弃
            p["source"] = "lab_publications"
            p["page"] = page_url
            ok.append(p)
    return ok


def merge_paper_sources(arxiv: list, epmc: list, lab: list, seed: list = None) -> list[dict]:
    """
    跨源合并去重：同标题（归一化比对）的论文合并为一条，sources 字段记录命中来源。
    价值：官网论文可补上 arXiv/PMC 缺失的条目，多源命中则互相印证，可信度更高。
    种子策略（seed）结果作为第 4 源参与合并——它按合作者网络过滤，是重名场景下的高置信来源。
    """
    merged: dict[str, dict] = {}

    def add(p: dict, src: str):
        key = loose(p.get("title"))[:70]
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
    for p in (seed or []):
        if not p.get("error"):
            add(p, "种子策略")
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
            r = get(url, headers=HEADERS, timeout=120)
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


def _download_bytes(url: str, timeout: int = 120, tries: int = 2) -> bytes:
    """带重试的二进制下载（PDF 等）；SSL 证书降级与 UA 由 fetch_common.get 统一处理"""
    last = None
    for i in range(tries):
        try:
            return get(url, headers=HEADERS, timeout=timeout).content
        except requests.RequestException as e:
            last = e
            time.sleep(3)
    raise RuntimeError(f"下载失败：{last}")


def find_oa_pdf_url(doi: str) -> str:
    """用 OpenAlex 查该 DOI 的开放获取 PDF 直链（无则返回空串）"""
    try:
        r = get(f"https://api.openalex.org/works/doi:{doi}",
                headers={"User-Agent": "advisor-agent/1.0 (mailto:advisor@example.com)"},
                timeout=20, check_status=False)
        if r.status_code != 200:
            return ""
        loc = (r.json().get("best_oa_location") or {})
        return loc.get("pdf_url") or ""
    except Exception:
        return ""


def fetch_pmc_fulltext(pmcid: str) -> str:
    """从 Europe PMC 取开放获取全文 XML 并转为纯文本（无则返回空串）"""
    try:
        r = get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
                headers=HEADERS, timeout=40, check_status=False)
        if r.status_code != 200:
            return ""
        xml = r.text
        xml = re.sub(r"(?is)<(ref-list|back|table-wrap|fig).*?</\1>", " ", xml)  # 去参考文献等
        text = re.sub(r"(?s)<[^>]+>", " ", xml)
        text = re.sub(r"\s+", " ", text).strip()
        return text if len(text) > 2000 else ""
    except Exception:
        return ""


def fetch_fulltext(identifier: str) -> dict:
    """
    通用全文获取（多级途径），支持：
      - arXiv id（如 2606.09669v2）
      - DOI（如 10.xxxx/xxxxx）→ OpenAlex 查 OA PDF → Europe PMC 全文
      - PDF 直链（如实验室官网的 /file/xxx.pdf）→ 直接下载
      - 本地 PDF 路径 → 直接解析
    成功返回 {"paper_id", "txt_file", "source", "chars", "preview"}；失败返回 {"error", "hint"}
    paper_id 可直接用于 paper_decision / deep_dive。
    """
    ident = identifier.strip().strip('"')
    paper_id, pdf_url, source = "", "", ""

    # 1) 本地 PDF
    if ident.lower().endswith(".pdf") and Path(ident).exists():
        paper_id = Path(ident).stem
        content = Path(ident).read_bytes()
        source = "本地PDF"
    # 2) PDF 直链 / 任意 http
    elif ident.startswith("http"):
        paper_id = re.sub(r"\.pdf$", "", ident.split("/")[-1], flags=re.I)[:80]
        content = _download_bytes(ident)
        source = "PDF直链"
    # 3) arXiv
    elif re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", ident):
        txt, _, _ = fetch_paper(ident)
        return {"paper_id": ident, "txt_file": str(txt), "source": "arXiv",
                "chars": len(txt.read_text(encoding="utf-8")),
                "preview": txt.read_text(encoding="utf-8")[:300]}
    # 4) DOI
    elif ident.lower().startswith("10."):
        paper_id = ident.replace("/", "_")
        # 4a. OpenAlex 找 OA PDF
        pdf_url = find_oa_pdf_url(ident)
        content = None
        if pdf_url:
            try:
                content = _download_bytes(pdf_url)
                source = f"OpenAlex OA ({pdf_url.split('/')[2] if '//' in pdf_url else ''})"
            except Exception:
                content = None
        # 4b. Europe PMC 全文
        if content is None:
            try:
                rs = get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                         params={"query": f'DOI:"{ident}"', "format": "json",
                                 "resultType": "core", "pageSize": 1},
                         headers=HEADERS, timeout=25, check_status=False)
                it = (rs.json().get("resultList", {}).get("result", []) or [{}])[0]
                pmcid = it.get("pmcid") or ""
                full = fetch_pmc_fulltext(pmcid) if pmcid else ""
                if full:
                    txt_file = PAPERS_DIR / f"{paper_id}.txt"
                    txt_file.write_text(full, encoding="utf-8")
                    return {"paper_id": paper_id, "txt_file": str(txt_file),
                            "source": f"Europe PMC 全文 ({pmcid})", "chars": len(full),
                            "preview": full[:300]}
            except Exception:
                pass
            return {"error": f"该论文（DOI: {ident}）未找到开放获取全文",
                    "hint": "非开放获取论文无法自动下载。可尝试：①去实验室官网 Publications 页找 [PDF]；"
                            "②作者主页/ResearchGate；③学校图书馆。拿到 PDF 后把本地路径传给 fetch_fulltext"}
    # 5) PMCID
    elif ident.upper().startswith("PMC"):
        full = fetch_pmc_fulltext(ident)
        if full:
            txt_file = PAPERS_DIR / f"{ident}.txt"
            txt_file.write_text(full, encoding="utf-8")
            return {"paper_id": ident, "txt_file": str(txt_file),
                    "source": "Europe PMC 全文", "chars": len(full), "preview": full[:300]}
        return {"error": f"{ident} 无开放获取全文"}
    else:
        return {"error": f"无法识别的标识符：{ident}",
                "hint": "支持 arXiv id / DOI / PDF 直链 / 本地 PDF 路径 / PMCID"}

    # 解析 PDF
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
    except Exception as e:
        return {"error": f"PDF 解析失败：{e}（可能不是 PDF 或已损坏）"}
    if len(text) < 1000:
        return {"error": "PDF 正文过短（可能是扫描版图片PDF，无法提取文字）"}
    txt_file = PAPERS_DIR / f"{paper_id}.txt"
    txt_file.write_text(text, encoding="utf-8")
    return {"paper_id": paper_id, "txt_file": str(txt_file), "source": source,
            "chars": len(text), "preview": text[:300]}


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