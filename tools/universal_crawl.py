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

    base_url, model = LONG_MODEL[PROVIDER]
    client = OpenAI(api_key=API_KEY, base_url=base_url)

    def _extract(html_text: str) -> tuple:
        cleaned = clean_html(html_text)
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": EXTRACT_PROMPT},
                      {"role": "user", "content": cleaned}],
            response_format={"type": "json_object"},
            temperature=0.1)
        raw = json.loads(r.choices[0].message.content)["teachers"]
        ok, dropped = [], []
        for t in raw:
            if t.get("name") and t["name"] in cleaned:
                t["detail_url"] = urljoin(url, t.pop("detail_path") or "") or None
                t["section"] = None
                ok.append(t)
            else:
                dropped.append(t.get("name"))
        return ok, dropped

    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    html_clean = clean_html(resp.text)

    ok, dropped = _extract(html_clean)

    # JS 动态页降级：requests 提取不到人时，用 Chrome headless 渲染再试
    if len(ok) == 0:
        try:
            from web_fetch import render_url
            print(f"⚠️ requests 未提取到教师({len(ok)}条)，疑似 JS 动态渲染，降级 Chrome headless...")
            rendered = render_url(url, max_chars=14000, budget_ms=30000)
            if rendered.get("error"):
                print(f"⚠️ 渲染失败({rendered['error']})，保留原始结果")
            else:
                ok2, dropped2 = _extract(rendered.get("text", ""))
                if len(ok2) > len(ok):
                    ok = ok2
                    dropped = dropped2
                    html_clean = clean_html(rendered.get("text", ""))
                    print(f"✅ 渲染后提取到 {len(ok)} 条")
                else:
                    print(f"⚠️ 渲染后仍未改善({len(ok2)}条)，保留原始结果")
        except Exception as e:
            print(f"⚠️ 渲染降级异常({e})，保留原始结果")

    if not ok and dropped:
        print(f"⚠️ 所有教师均未通过原文校验（疑似幻觉）：{dropped[:5]}...")

    page_teachers = merge_by_name(ok)
    out_file = DATA_DIR / f"faculty_{site}.json"

    # 合并式落盘：已有名单按姓名保留，本页新增教师合进去，不覆盖丢数据。
    # 支持分页师资页多次 add_school 累加（北大智能学院 5 页等场景）。
    existing = []
    if out_file.exists():
        try:
            existing = json.load(open(out_file, encoding="utf-8")).get("teachers", [])
        except Exception:
            existing = []
        if existing:
            # 已收录过的页面重复调用时，返回现有名单即可，不再次覆盖
            if url in {t.get("source_url") for t in existing}:
                print(f"ℹ️ 页面 {url} 已收录过，现有名单 {len(existing)} 人保持不变")
                return
            # 已有记录是 sections 形态，直接按名保留；本页新增的才补入
            combined = {t["name"]: t for t in existing}
            for t in page_teachers:
                combined.setdefault(t["name"], t)
            merged = list(combined.values())
        else:
            merged = page_teachers
    else:
        merged = page_teachers

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"source_url": url, "crawl_date": date.today().isoformat(),
                   "count": len(merged), "extractor": "llm",
                   "teachers": merged}, f, ensure_ascii=False, indent=2)

    print(f"提取 {len(ok)} 条 → 校验通过 {len(merged)} 人 → {out_file}"
          f"（跨页合并，累计 {len(merged)} 人）")
    if dropped:
        print(f"⚠️ {len(dropped)} 条未通过原文校验（疑似幻觉），已丢弃：{dropped}")


if __name__ == "__main__":
    main()