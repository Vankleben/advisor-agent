"""
工具一：师资名单抓取器 v2.2
架构：通用层(fetch/合并/落盘) + 站点适配器(每个网站一个 parse 函数)
用法：python tools/crawl_faculty.py collegeai   (清华人工智能学院)
      python tools/crawl_faculty.py life        (清华生命科学院)
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import re
import sys
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import date
from pathlib import Path

from fetch_common import get

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# ============ 通用层：换任何学校都不动 ============

def fetch(url: str) -> str:
    """抓名单页 HTML（UA/编码/SSL 由 fetch_common 统一处理）。"""
    return get(url, timeout=15).text


def merge_by_name(records: list[dict]) -> list[dict]:
    """同名合并：一人多岗时，板块身份合并为列表。"""
    merged = {}
    for t in records:
        if t["name"] in merged:
            entry = merged[t["name"]]
            if t["section"] not in entry["sections"]:
                entry["sections"].append(t["section"])
        else:
            t["sections"] = [t.pop("section")]
            merged[t["name"]] = t
    return list(merged.values())


# ============ 特异层：每个网站一个适配器 ============

def parse_collegeai(html: str, base_url: str) -> list[dict]:
    """适配器 #1：清华大学人工智能学院（卡片式布局）"""
    soup = BeautifulSoup(html, "lxml")
    records = []
    current_section = None
    for box in soup.select("div.box"):
        h3 = box.select_one("h3.h3-5")
        if h3:
            current_section = h3.get_text(strip=True)
        for li in box.select("ul.ls16 li"):
            img = li.select_one(".img img")
            if not img or not img.get("src"):
                continue  # 真人卡片必有照片；src 为空的是页脚垃圾条目
            name_tag = li.select_one(".txt h4")
            if not name_tag:
                continue
            title_tag = li.select_one(".txt p")
            dirs = [h.get_text(strip=True)
                    for h in li.select(".bottom h4.l2")
                    if h.get_text(strip=True)]
            email_tag = li.select_one(".bottom p")
            a = li.select_one("a.a")
            records.append({
                "name": name_tag.get_text(strip=True),
                "title": (title_tag.get_text(strip=True)
                          if title_tag and title_tag.get_text(strip=True) else None),
                "section": current_section,
                "research": dirs[0] if dirs else None,
                "email": (email_tag.get_text(strip=True)
                          if email_tag and "@" in email_tag.get_text() else None),
                "detail_url": urljoin(base_url, a["href"]) if a and a.get("href") else None,
            })
    return records


def parse_life(html: str, base_url: str) -> list[dict]:
    """适配器 #2：清华大学生命科学学院（名单式布局）"""
    soup = BeautifulSoup(html, "lxml")
    records = []
    catalogs = [c.get_text(strip=True) for c in soup.select(".catalog")]
    blocks = soup.select(".pepolelist")
    for series, block in zip(catalogs[1:], blocks):
        group = None
        for child in block.find_all(["div", "ul"], recursive=False):
            cls = child.get("class") or []
            if "subcatalog" in cls:
                group = child.get_text(strip=True)
            elif "clearfix" in cls:
                for li in child.find_all("li", recursive=False):
                    a = li.find("a", href=True)
                    if not a:
                        continue
                    name = (a.get("title") or a.get_text(strip=True)).replace("　", "")
                    records.append({
                        "name": name,
                        "title": None,
                        "section": series,
                        "research": group,
                        "email": None,
                        "detail_url": urljoin(base_url, a["href"]),
                    })
    return records


# ---- 适配器 #3：西湖大学工学院（教师数据内嵌在页面 JS 的 teamList 里，无需 LLM 抽取）----
# 该站导航是 JS 路由（页面无 <a href>），但服务端把整份名录写进了内嵌对象数组：
#   { imgUrl, name: "某某博士", lab: "实验室名", area: "系名", direct: "研究方向", url: "个人主页", sideline: "学院归属" }
# 姓名统一带"博士"后缀，这里剥掉以便卡片检索；职称/邮箱名录里没有，由 enrich + 卡片阶段从个人主页提取。

WESTLAKE_CS_AREAS = ("人工智能系", "电子信息工程系", "先进工程科学与技术中心")
WESTLAKE_CS_KEYWORDS = ("智能", "计算", "数据", "机器学习", "人工智能", "脑机", "信息",
                        "算法", "视觉", "语言", "机器人", "统计", "模型", "模拟", "仿真",
                        "建模", "数字")


def _js_field(block: str, key: str) -> str:
    """取内嵌 JS 对象里的字符串字段（值含中文/逗号，不能用 split 解析）。"""
    m = re.search(rf'{key}\s*:\s*"([^"]*)"', block)
    return m.group(1).strip() if m else ""


def parse_westlake_engineering(html: str, base_url: str, cs_only: bool = True) -> list[dict]:
    """适配器 #3：西湖大学工学院教师名录（按姓名/系别/实验室/个人主页结构化提取）。

    cs_only=True 时只保留与计算机相关或交叉的：人工智能系、电子信息工程系、
    先进工程科学与技术中心，以及实验室或研究方向含计算类关键词的跨系教师
    （材料/化学等纯实验方向不收）。
    """
    blocks = [b for b in re.findall(r"\{[^{}]*\}", html)
              if "name:" in b and "sideline:" in b]
    records = []
    for b in blocks:
        name = _js_field(b, "name")
        if not name:
            continue
        area = _js_field(b, "area")
        lab = _js_field(b, "lab")
        direct = _js_field(b, "direct")
        url = _js_field(b, "url")
        sideline = _js_field(b, "sideline")
        if cs_only and not (area in WESTLAKE_CS_AREAS
                            or any(k in lab + direct for k in WESTLAKE_CS_KEYWORDS)):
            continue
        records.append({
            "name": re.sub(r"博士$", "", name).strip(),
            "title": None,                      # 名录不含职称，卡片阶段从个人主页提取
            "section": area or sideline or None,
            "research": direct or lab or None,
            "email": None,
            "detail_url": url or None,
            "lab": lab,                         # 附加字段，卡片阶段可参考
            "sideline": sideline,
        })
    return records


# ---- 适配器 #4：深圳医学科学院（SMART）导师风采 ----
# 条目形如：<div class="item itemlist" data-title="姓名" data-xueke=".." data-danwei="..">
#              <a href="/smart-fellow/xxx">…</a>
# 姓名在 data-title 属性里，详情页链接在 href（数字 id 与拼音 slug 两种形态并存）。
# 名录分页，每页 20 条；页面是服务端渲染的，普通抓取即可。

SMART_FELLOW_PAGES = ["https://smart.org.cn/smart-fellow"] + [
    f"https://smart.org.cn/smart-fellow?index=&unit=&subject=&page={n}"
    for n in range(2, 6)          # 实测 5 页；名录增长后在 range 上界加页
]


def parse_smart_fellows(html: str, base_url: str) -> list[dict]:
    """适配器 #4：SMART 导师名录单页解析（姓名 + 详情页）。职称/研究方向在详情页，由后续步骤提取。"""
    records = []
    for m in re.finditer(r'<div class="item itemlist"[^>]*data-title="([^"]+)"[^>]*>\s*'
                         r'<a href="([^"]+)"', html):
        name, href = m.group(1).strip(), m.group(2).strip()
        if not name or not href:
            continue
        records.append({
            "name": name,
            "title": None,                 # 详情页里才有职称，卡片阶段提取
            "section": "SMART 导师",
            "research": None,              # 同上
            "email": None,
            "detail_url": urljoin(base_url, href),
        })
    return records


# ---- 适配器 #5：清华大学医学院·基础医学院（教研系列）----
# 列表项结构：<li><a href="../../../info/1139/xxxx.htm"><div class="scale">…</div>
#               <div class="con"><h3>张三 Zhang San</h3></div></a></li>
# 导航菜单同样是 <li><h3>，用 href 是否含 "/info/" 区分（导航链接不含）。
# 姓名取 h3 里的中文名（"张三 Zhang San" → "张三"），纯英文名保留全名。

THUMED_PAGES = ["http://www.med.tsinghua.edu.cn/jy/szdw1/jcyxy/jyxl.htm"] + [
    f"http://www.med.tsinghua.edu.cn/jy/szdw1/jcyxy/jyxl/{n}.htm" for n in range(1, 4)
] + [                                    # 临床医学院·教研系列（2 页）
    "http://www.med.tsinghua.edu.cn/jy/szdw1/lcyxy/lcjyxl.htm",
    "http://www.med.tsinghua.edu.cn/jy/szdw1/lcyxy/lcjyxl/1.htm",
    "http://www.med.tsinghua.edu.cn/jy/szdw1/lcyxy/lcjyxl/2.htm",
] + [                                    # 药学院·教研系列（2 页）
    "http://www.med.tsinghua.edu.cn/jy/szdw1/yxy1/jyxl.htm",
    "http://www.med.tsinghua.edu.cn/jy/szdw1/yxy1/jyxl/1.htm",
    "http://www.med.tsinghua.edu.cn/jy/szdw1/yxy1/jyxl/2.htm",
]

# 同一网站的"生物医学工程学院"（医学影像/神经工程/微纳医学与组织工程三个方向）
THUMED_BME_PAGES = [
    "http://www.med.tsinghua.edu.cn/jy/szdw1/sygc/jyxl1.htm",
    "http://www.med.tsinghua.edu.cn/jy/szdw1/sygc/jyxl1/yxyx.htm",
    "http://www.med.tsinghua.edu.cn/jy/szdw1/sygc/jyxl1/sjgc.htm",
    "http://www.med.tsinghua.edu.cn/jy/szdw1/sygc/jyxl1/wnyxyzzgc.htm",
]


def parse_thumed(html: str, base_url: str) -> list[dict]:
    """适配器 #5：清华医学院教研系列名录（姓名 + 个人页链接）。同一模板覆盖多个院系。"""
    section = "基础医学院·教研系列"
    for key, label in (("/sygc/", "生物医学工程学院·教研系列"),
                       ("/lcyxy/", "临床医学院·教研系列"),
                       ("/yxy1/", "药学院·教研系列")):
        if key in base_url:
            section = label
            break
    soup = BeautifulSoup(html, "lxml")
    records = []
    for li in soup.find_all("li"):
        h3 = li.find("h3")
        a = li.find("a", href=True)
        if not h3 or not a or "/info/" not in a["href"]:
            continue
        text = h3.get_text(strip=True)
        m = re.match(r"[\u4e00-\u9fa5]{2,4}", text)
        records.append({
            "name": m.group(0) if m else text,
            "title": None,                 # 职称在个人页，卡片阶段提取
            "section": section,
            "research": None,
            "email": None,
            "detail_url": urljoin(base_url, a["href"]),
        })
    return records


# ---- 适配器 #6：西湖大学生命科学学院 ----
# 列表项：<a href="https://www.westlake.edu.cn/faculty/<slug>.html">
#           <p class="con_ev_name">张三博士</p><p class="con_ev_name">Zhang San, Ph.D.</p></a>
# 个人主页与工学院同一套模板，正文由 enrich_faculty.parse_westlake_detail 抽取。


def parse_westlake_sls(html: str, base_url: str) -> list[dict]:
    """适配器 #6：西湖大学生命科学学院名录（姓名在 p.con_ev_name，链接指向个人主页）。"""
    soup = BeautifulSoup(html, "lxml")
    records = []
    for a in soup.find_all("a", href=True):
        if "/faculty/" not in a["href"]:
            continue                      # 图片链接无姓名节点，跳过
        names = [p.get_text(strip=True) for p in a.select("p.con_ev_name")]
        if not names:
            continue
        records.append({
            "name": re.sub(r"(博士|教授)$", "", names[0]).strip(),
            "title": None,
            "section": "生命科学学院",
            "research": None,
            "email": None,
            "detail_url": urljoin(base_url, a["href"]),
        })
    return records


# ---- 适配器 #7：北大生命科学学院·博士生导师 ----
# 名录条目锚文本把信息都写在链接文字里，形如：
#   "张三 研究员 具有招生资格 Email：zhangsan (AT) pku.edu.cn 所属实验室：张三实验室 实验室地址：…"
# 姓名在开头，其后跟职称；"具有招生资格"是招生信号，一并记下供筛选。
# 此前用 LLM 抽该页会截断（只取到前 73 人）且把详情链接错填成列表页，故改为确定性解析。

PKUBIO_BOARD = "https://www.bio.pku.edu.cn/homes/Index/news_szll_zy/16/16.html"


def parse_pkubio(html: str, base_url: str) -> list[dict]:
    """适配器 #7：北大生科博士生导师名录（姓名/职称/邮箱/实验室 + 个人页链接）。"""
    soup = BeautifulSoup(html, "lxml")
    records = []
    for a in soup.find_all("a", href=True):
        if "news_cont_jl" not in a["href"]:
            continue
        text = a.get_text(" ", strip=True).replace("\u3000", " ")
        m = re.match(r"([\u4e00-\u9fa5]{2,4}|[A-Za-z][A-Za-z .\-']{2,30})", text)
        if not m:
            continue
        rest = text[m.end():]
        title = next((t for t in ("副教授", "副研究员", "助理教授", "教授", "研究员", "讲师")
                      if t in rest), None)
        email = re.search(r"[a-zA-Z0-9._%+-]+ \(AT\) [a-zA-Z0-9.\-]+", text)
        lab = re.search(r"所属实验室：\s*(\S+)", text)
        records.append({
            "name": m.group(1).strip(),
            "title": title,
            "section": "生命科学学院·博士生导师",
            "research": None,              # 研究方向在个人页，卡片阶段提取
            "email": email.group(0).replace("(AT)", "@").replace(" ", "") if email else None,
            "detail_url": urljoin(base_url, a["href"]),
            "recruiting": "具有招生资格" in text,   # 名录页自带的招生信号
            "lab": lab.group(1) if lab else None,
        })
    return records


# ---- 适配器 #8：西湖大学全校导师目录 ----
# https://www.westlake.edu.cn/about/faculty/ 的 memberList 内嵌了全校导师：
#   { imgUrl, name: "张三博士", nameEn, school: "生命科学学院", subject: "研究方向</br>实验室", url: "个人主页" }
# 各学院官网（工学院/生命科学学院/医学院）只列本院部分人，这里是唯一完整来源（304 人）。
# 按学院关键词筛选：生命科学相关（含兼聘）→ wlls。

WESTLAKE_ALL_URL = "https://www.westlake.edu.cn/about/faculty/"
WESTLAKE_LIFE_MED = ("生命科学学院", "医学院")


def parse_westlake_all(html: str, base_url: str,
                       school_filter: tuple = WESTLAKE_LIFE_MED) -> list[dict]:
    """适配器 #8：西湖大学导师总目录（按学院筛选，默认只留生命科学/医学相关，含兼聘）。"""
    records = []
    for b in re.findall(r"\{([^{}]*name:\s*\"[^\"]+\"[^{}]*)\}", html):
        name = _js_field(b, "name")
        school = _js_field(b, "school")
        subject = _js_field(b, "subject")
        url = _js_field(b, "url")
        if not name or (school_filter and not any(k in school for k in school_filter)):
            continue
        records.append({
            "name": re.sub(r"博士$", "", name).strip(),
            "title": None,
            "section": school,
            "research": subject.replace("<br/>", " ").replace("</br>", " ").strip() or None,
            "email": None,
            "detail_url": url or None,
        })
    return records


# ---- 适配器 #9：正文由 JS 渲染的站点（先渲染取链接，再从 <a> 的文字/href 抽人）----
# 北大前沿交叉学科研究院名录：requests 拿到的 HTML 只有导航，渲染后 <a> 的文字才是人名，
# href 指向个人页 /info/<栏目>/<id>.htm。故该站走 render 模式（见 SITES 表第三项）。

def parse_aais_rendered(page: dict, base_url: str) -> list[dict]:
    """适配器 #9：渲染后页面（dict 含 links）→ 姓名 + 所属院系 + 个人页链接。

    渲染后每条链接的文字形如："张三 所在院系：智能学院"，姓名在首行、院系在其后。"""
    records = []
    for link in page.get("links") or []:
        url = link.get("url") or ""
        if "/info/" not in url:
            continue
        text = re.sub(r"\s+", " ", (link.get("text") or "")).strip()
        m = re.match(r"([\u4e00-\u9fa5]{2,4})(?=\s|$)", text)
        if not m:
            continue                      # 只要"人名 → 个人页"这类链接
        dept = re.search(r"所在院系：\s*([^\s：]+)", text)
        records.append({
            "name": m.group(1),
            "title": None,
            "section": dept.group(1) if dept else "前沿交叉学科研究院",
            "research": None,
            "email": None,
            "detail_url": url,
        })
    return records


# ============ 站点注册表：加新学校只动这里 ============

SITES = {
    "collegeai": ("https://collegeai.tsinghua.edu.cn/rydw.htm", parse_collegeai),
    "life": ("https://life.tsinghua.edu.cn/szdw/jzyg1.htm", parse_life),
    "wlcs": ("https://engineering.westlake.edu.cn/Faculty/Directory/",
             parse_westlake_engineering),
    "smart": (SMART_FELLOW_PAGES, parse_smart_fellows),
    "thumed": (THUMED_PAGES, parse_thumed),
    "thubme": (THUMED_BME_PAGES, parse_thumed),
    "wlsls": ("https://sls.westlake.edu.cn/Our_Faculty/", parse_westlake_sls),
    "pkubio": (PKUBIO_BOARD, parse_pkubio),
    "wlls": (WESTLAKE_ALL_URL, parse_westlake_all),
    # 第三项 "render" = 该站正文由 JS 渲染，parser 收到的是渲染结果（含 links），不是原始 HTML
    "pkuais": ("http://www.aais.pku.edu.cn/szdw/swyxkxkyjzx1.htm",
               parse_aais_rendered, "render"),
}


def main():
    args = sys.argv[1:]
    site = args[0] if args and not args[0].startswith("--") else "collegeai"
    if site not in SITES:
        print(f"未知站点 {site}，可选：{list(SITES)}")
        return
    urls, parser = SITES[site][:2]
    render_mode = len(SITES[site]) > 2 and SITES[site][2] == "render"
    if isinstance(urls, str):
        urls = [urls]

    # --only 名字1,名字2：只收录指定的人（用于"先收这一位"，避免整站批量跑卡片）
    only = set()
    if "--only" in args:
        idx = args.index("--only")
        if idx + 1 < len(args):
            only = {n.strip() for n in args[idx + 1].split(",") if n.strip()}

    records = []
    for u in urls:
        try:
            if render_mode:
                from web_fetch import render_url
                page = render_url(u, max_chars=20000, budget_ms=60000)
                if page.get("error"):
                    print(f"⚠️ 渲染失败：{u}（{page['error']}）")
                    continue
                records += parser(page, u)
            else:
                records += parser(fetch(u), u)
        except Exception as e:
            print(f"⚠️ 页面抓取失败：{u}（{type(e).__name__}: {e}）")

    if not records:
        print("❌ 没有抓到任何记录，保留原有名单不变（不覆盖）")
        return

    if only:
        records = [r for r in records if r["name"] in only]
        missing = only - {r["name"] for r in records}
        if missing:
            print(f"⚠️ 名录里没找到：{sorted(missing)}")

    teachers = merge_by_name(records)
    output = {
        "source_url": " | ".join(urls),
        "crawl_date": date.today().isoformat(),
        "count": len(teachers),
        "teachers": teachers,
    }
    out_file = DATA_DIR / f"faculty_{site}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[{site}] 抓取完成：{len(teachers)} 位（去重后）→ {out_file}")
    from collections import Counter
    for section, n in Counter(s for t in teachers for s in t["sections"]).items():
        print(f"  {section}: {n} 人")


if __name__ == "__main__":
    main()