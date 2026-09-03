"""
工具五：通用师资抓取器（LLM 驱动，适配任意学校）
用法：python tools/universal_crawl.py <师资页URL> <站点代号>
"""
import json
import re
import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import date
from pathlib import Path
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "tools"))
from config import PROVIDER, API_KEY
from crawl_faculty import merge_by_name, HEADERS

LONG_MODEL = {"moonshot": ("https://api.moonshot.cn/v1", "moonshot-v1-32k"),
              "deepseek": ("https://api.deepseek.com", "deepseek-chat")}

EXTRACT_PROMPT = """你是网页结构化提取器。我给你一个高校师资名单页的 HTML（已清洗），请提取页面上所有教职工。

铁律：
1. 只允许提取 HTML 中真实存在的人名，严禁补充你认识的任何学者；
2. 页面上没有的信息填 null，禁止编造；
3. 导航栏、页脚里的文字不是人名，不要提取；
4. detail_path 填该老师名字链接的 href 原样值（可能是相对路径）；
5. 输出合法 JSON：{"teachers": [{"name": "...", "title": "职称或null", "research": "研究方向或null", "email": "邮箱或null", "detail_path": "href或null"}]}
只输出 JSON，不要任何其他文字。"""


def clean_html(html: str, max_chars: int = 14000) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "header", "footer"]):
        tag.decompose()
    body = soup.body or soup
    text = str(body)
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars]


def main():
    if len(sys.argv) < 3:
        print("用法：python tools/universal_crawl.py <师资页URL> <站点代号>")
        return
    url, site = sys.argv[1], sys.argv[2]

    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    html_clean = clean_html(resp.text)

    base_url, model = LONG_MODEL[PROVIDER]
    client = OpenAI(api_key=API_KEY, base_url=base_url)
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": EXTRACT_PROMPT},
                  {"role": "user", "content": html_clean}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    raw = json.loads(r.choices[0].message.content)["teachers"]

    ok, dropped = [], []
    for t in raw:
        if t.get("name") and t["name"] in html_clean:
            t["detail_url"] = urljoin(url, t.pop("detail_path") or "") or None
            t["section"] = None
            ok.append(t)
        else:
            dropped.append(t.get("name"))

    teachers = merge_by_name(ok)
    out_file = DATA_DIR / f"faculty_{site}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"source_url": url, "crawl_date": date.today().isoformat(),
                   "count": len(teachers), "extractor": "llm",
                   "teachers": teachers}, f, ensure_ascii=False, indent=2)

    print(f"提取 {len(raw)} 条 → 校验通过 {len(teachers)} 人 → {out_file}")
    if dropped:
        print(f"⚠️ {len(dropped)} 条未通过原文校验（疑似幻觉），已丢弃：{dropped}")


if __name__ == "__main__":
    main()