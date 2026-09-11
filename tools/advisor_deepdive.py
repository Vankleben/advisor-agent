"""
工具九：M2 导师深潜 v1.3
改动：1. 兼容旧格式卡片（homepage_candidates 为字符串数组时，直接跳过，走 fallback）
      2. fallback 触发条件改为"candidates 为空 *或* 全部抓取失败"，不再被 candidates 非空挡住
用法：python tools/advisor_deepdive.py 董胤蓬
      python tools/advisor_deepdive.py 董胤蓬 --url https://xxx.github.io
产出：data/deepdive/{name}_report.json        深潜报告
      data/deepdive/{name}_src{i}.txt         信源原文缓存
"""
import json
import re
import sys
import datetime
from html import unescape
from pathlib import Path
import requests
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUT_DIR = DATA_DIR / "deepdive"
sys.path.insert(0, str(BASE_DIR))
from config import PROVIDER, API_KEY

PROVIDERS = {
    "moonshot": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
}
P = PROVIDERS[PROVIDER]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/120.0 Safari/537.36"}
MAX_SRC_CHARS = 8000

DEEP_PROMPT = """你是导师深潜分析员，服务对象是一名想找实验室的 CS 大三学生。
我会给你某位老师多个网页的正文（已编号），请提取对学生选导师真正有用的深度情报。

铁律：
1. 只允许使用我提供的网页原文，禁止使用你自己的任何背景知识；
2. 每条情报的 evidence 必须是该条情报 source 字段所指向来源中的【连续原句】，逐字复制，
   禁止改写、概括、拼接；分散的用数组给多条；找不到原文支撑的判断不要输出，宁缺勿滥；
3. 信源优先级：来源编号越小越可信（个人主页 > 实验室页 > 学院官网）。同一情报多来源冲突时，
   以小编号来源为准，并在 note 里说明冲突；
4. 没有 News/动态板块就留空数组，严禁编造。

输出 JSON：
{"research_now": [{"point": "近期研究重点", "evidence": ["原句"], "source": 1, "note": ""}],
 "research_timeline": [{"point": "研究轨迹/方向漂移（近3-5年从什么转向什么，或一直稳定）", "evidence": ["原句"], "source": 1, "note": ""}],
 "lab_culture":   [{"point": "组内风格线索（会议/作息/氛围）", "evidence": ["原句"], "source": 1, "note": ""}],
 "recruitment":   [{"point": "招生意向与要求", "evidence": ["原句"], "source": 1, "note": ""}],
 "career_outcomes": [{"point": "学生毕业去向", "evidence": ["原句"], "source": 1, "note": ""}],
 "recent_activity": [{"point": "近期动态（论文/获奖/新闻）", "evidence": ["原句"], "source": 1, "note": ""}],
 "github_footprint": [{"point": "开源/工程足迹（GitHub仓库/代码、工具、活跃度线索）", "evidence": ["原句"], "source": 1, "note": ""}],
 "fit_questions": ["结合以上情报，给用户的3-5个套磁/面试前该问的具体问题"],
 "summary": "一句话深潜结论（要不要重点考虑这位老师，为什么）"}

网页原文：
{sources}"""


# ============ 通用层：抓取与校验 ============

def fetch_text(url: str) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
    except requests.exceptions.SSLError:
        print(f"⚠️ SSL 证书验证失败({url})，降级跳过验证")
        r = requests.get(url, headers=HEADERS, timeout=20, verify=False)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    html = r.text
    text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = unescape(re.sub(r"(?s)<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text).strip()
    # SSL 降级后内容仍很短（被拦截）→ 降级 Chrome headless 渲染
    if len(text) < 50:
        try:
            from web_fetch import render_url
            print(f"⚠️ 内容过短({len(text)}字符)，降级 Chrome headless 渲染...")
            rendered = render_url(url, max_chars=8000, budget_ms=20000)
            if not rendered.get("error") and len(rendered.get("text", "")) > len(text):
                text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", rendered.get("text", ""))
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
                print(f"✅ 渲染后获取到 {len(text)} 字符")
        except Exception:
            pass
    return text


def flatten(text: str) -> str:
    return re.sub(r"\s+", "", text)


def load_card(name: str, site: str = "") -> dict:
    files = [DATA_DIR / f"cards_{site}.json"] if site else sorted(DATA_DIR.glob("cards_*.json"))
    for f in files:
        if not f.exists():
            continue
        with open(f, encoding="utf-8") as fp:
            for c in json.load(fp).get("cards", []):
                if c.get("name") == name:
                    return c
    raise LookupError(f"卡片库中找不到 {name}，请先收录并生成卡片")


def load_enriched(name: str, site: str = "") -> dict:
    files = [DATA_DIR / f"faculty_{site}_enriched.json"] if site else sorted(DATA_DIR.glob("faculty_*_enriched.json"))
    for f in files:
        if not f.exists():
            continue
        with open(f, encoding="utf-8") as fp:
            for t in json.load(fp).get("teachers", []):
                if t.get("name") == name:
                    return t
    return {}


def verify_report(report: dict, src_texts: list) -> list:
    flats = [flatten(t) for t in src_texts]
    warnings = []
    for section in ("research_now", "research_timeline", "lab_culture", "recruitment",
                    "career_outcomes", "recent_activity", "github_footprint"):
        for i, item in enumerate(report.get(section, [])):
            src_idx = int(item.get("source", 0)) - 1
            if not (0 <= src_idx < len(flats)):
                warnings.append(f"⚠️ {section}[{i}] source 编号越界：{item.get('point', '')}")
                continue
            for q in (item.get("evidence") or []):
                if flatten(str(q)) not in flats[src_idx]:
                    warnings.append(f"⚠️ {section}[{i}] 的 evidence 在来源{src_idx + 1}中找不到："
                                    f"{str(q)[:50]}...")
    return warnings


# ============ 主流程 ============

def run_deepdive(client: OpenAI, name: str, site: str = "", url: str = "") -> dict:
    # 1. 尝试加载卡片；若找不到但提供了 url，则跳过卡片（卡片非必需）
    hpc_urls = []
    try:
        card = load_card(name, site)
        hpc = card.get("homepage_candidates") or []
        if hpc and isinstance(hpc[0], dict):
            hpc_urls = [c["url"] for c in hpc if c.get("type") != "other" and c.get("url")]
    except LookupError:
        if url:
            print(f"ℹ️ 卡片库中未找到 {name}，使用提供的 URL: {url}")
        else:
            return {"error": f"卡片库中找不到 {name}，请先收录并生成卡片（add_school + enrich + batch）"}

    candidates = ([url] if url else []) + hpc_urls
    candidates = list(dict.fromkeys(candidates))[:3]

    # 2. 逐个抓取 candidates（编号 = 信源优先级）
    OUT_DIR.mkdir(exist_ok=True)
    src_texts, src_urls, failed = [], [], []
    for u in candidates:
        try:
            t = fetch_text(u)[:MAX_SRC_CHARS]
            src_texts.append(t)
            src_urls.append(u)
        except Exception as e:
            failed.append(f"{u} 抓取失败：{e}")

    # 3. fallback：candidates 为空，或全部抓取失败时，从 enriched 读 detail_text
    used_fallback = False
    if not src_texts:
        enriched = load_enriched(name, site)
        detail = (enriched.get("detail") or {})
        detail_text = detail.get("detail_text", "")
        detail_url = enriched.get("detail_url", "")
        if detail_text and not detail.get("error"):
            src_texts.append(detail_text[:MAX_SRC_CHARS])
            src_urls.append(detail_url or "学校官网详情页（已缓存正文）")
            used_fallback = True

    if not src_texts:
        return {"error": f"{name} 的卡片里没有 homepage_candidates，enriched 文件里也没找到详情页正文，"
                         f"请用 --url 手动提供个人主页网址",
                "fetch_failures": failed}

    # 4. 缓存原文
    for i, t in enumerate(src_texts, 1):
        (OUT_DIR / f"{name}_src{i}.txt").write_text(
            f"[{src_urls[i-1]}]\n{t}", encoding="utf-8")

    sources_block = "\n".join(
        f"【来源{i + 1}】{t}" for i, t in enumerate(src_texts))

    # 5. LLM 深潜提取 + 反幻觉校验
    prompt = DEEP_PROMPT.replace("{sources}", sources_block)
    resp = client.chat.completions.create(
        model=P["model"], temperature=0.1,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}])
    report = json.loads(resp.choices[0].message.content)
    warnings = verify_report(report, src_texts)

    # 6. 存档
    result = {"name": name, "date": datetime.date.today().isoformat(),
              "sources": src_urls, "report": report,
              "verification_warnings": warnings,
              "fetch_failures": failed,
              "used_fallback": used_fallback}
    out = OUT_DIR / f"{name}_report.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[M2] 深潜完成 → {out.name}；{len(warnings)} 条引句未过校验；{len(failed)} 个信源抓取失败"
          f"{'；使用 fallback（学校详情页正文）' if used_fallback else ''}")
    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    name = args[0]
    manual_url = args[args.index("--url") + 1] if "--url" in args else ""
    site = args[args.index("--site") + 1] if "--site" in args else ""
    client = OpenAI(api_key=API_KEY, base_url=P["base_url"])
    print(json.dumps(run_deepdive(client, name, site, manual_url),
                     ensure_ascii=False, indent=2))