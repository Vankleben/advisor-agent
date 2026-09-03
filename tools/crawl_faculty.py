"""
工具一：师资名单抓取器 v2.2
架构：通用层(fetch/合并/落盘) + 站点适配器(每个网站一个 parse 函数)
用法：python tools/crawl_faculty.py collegeai   (清华人工智能学院)
      python tools/crawl_faculty.py life        (清华生命科学院)
"""
import json
import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import date
from pathlib import Path

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# ============ 通用层：换任何学校都不动 ============

def fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


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


# ============ 站点注册表：加新学校只动这里 ============

SITES = {
    "collegeai": ("https://collegeai.tsinghua.edu.cn/rydw.htm", parse_collegeai),
    "life": ("https://life.tsinghua.edu.cn/szdw/jzyg1.htm", parse_life),
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