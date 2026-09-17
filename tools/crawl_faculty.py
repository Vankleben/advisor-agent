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


# ============ 站点注册表：加新学校只动这里 ============

SITES = {
    "collegeai": ("https://collegeai.tsinghua.edu.cn/rydw.htm", parse_collegeai),
    "life": ("https://life.tsinghua.edu.cn/szdw/jzyg1.htm", parse_life),
    "wlcs": ("https://engineering.westlake.edu.cn/Faculty/Directory/",
             parse_westlake_engineering),
}


def main():
    site = sys.argv[1] if len(sys.argv) > 1 else "collegeai"
    if site not in SITES:
        print(f"未知站点 {site}，可选：{list(SITES)}")
        return
    url, parser = SITES[site]

    teachers = merge_by_name(parser(fetch(url), url))
    output = {
        "source_url": url,
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