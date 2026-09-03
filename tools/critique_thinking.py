"""
工具九：M2 导师深潜
用法：python tools/advisor_deepdive.py 董胤蓬
      python tools/advisor_deepdive.py 董胤蓬 --url https://xxx.github.io
产出：data/deepdive/{name}_report.json        深潜报告
      data/deepdive/{name}_src{i}.txt         信源原文缓存
依赖：data/cards_*.json 中卡片须含 homepage_candidates 字段（batch_cards.py 已生成）
注意：prompt 含 JSON 示例，禁止用 .format()，统一用 .replace("{sources}", ...) 填变量
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
sys.path.insert(0, str(BASE_DIR / "tools"))
from config import PROVIDER, API_KEY

PROVIDERS = {
    "moonshot": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
}
P = PROVIDERS[PROVIDER]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/120.0 Safari/537.36"}
MAX_SRC_CHARS = 8000   # 单个信源截断长度，防止撑爆上下文

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
 "lab_culture":   [{"point": "组内风格线索（会议/作息/氛围）", "evidence": ["原句"], "source": 1, "note": ""}],
 "recruitment":   [{"point": "招生意向与要求", "evidence": ["原句"], "source": 1, "note": ""}],
 "career_outcomes": [{"point": "学生毕业去向", "evidence": ["原句"], "source": 1, "note": ""}],
 "recent_activity": [{"point": "近期动态（论文/获奖/新闻）", "evidence": ["原句"], "source": 1, "note": ""}],
 "fit_questions": ["结合以上情报，给用户的3-5个套磁/面试前该问的具体问题"],
 "summary": "一句话深潜结论（要不要重点考虑这位老师，为什么）"}

网页原文：
{sources}"""


# ============ 通用层：抓取与校验 ============

def fetch_text(url: str) -> str:
    """抓取网页并抽正文：去 script/style/标签，压空白。失败抛异常由上层处理"""
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    html = r.text
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = unescape(re.sub(r"(?s)<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", text).strip()


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


def verify_report(report: dict, src_texts: list) -> list:
    """反幻觉校验：每条 evidence 必须能在其 source 指向的原文中原样搜到"""
    flats = [flatten(t) for t in src_texts]
    warnings = []
    for section in ("research_now", "lab_culture", "recruitment",
                    "career_outcomes", "recent_activity"):
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
    # 1. 组置信源：手动 URL 优先，其次卡片里的 homepage_candidates（已按可信度排序）
    card = load_card(name, site)
    candidates = ([url] if url else []) + (card.get("homepage_candidates") or [])
    candidates = list(dict.fromkeys(candidates))[:3]
    if not candidates:
        return {"error": f"{name} 的卡片里没有 homepage_candidates，"
                         f"请用 --url 手动提供个人主页网址"}

    # 2. 逐个抓取（编号 = 信源优先级），缓存原文
    OUT_DIR.mkdir(exist_ok=True)
    src_texts, failed = [], []
    for i, u in enumerate(candidates, 1):
        try:
            t = fetch_text(u)[:MAX_SRC_CHARS]
            (OUT_DIR / f"{name}_src{i}.txt").write_text(f"[{u}]\n{t}", encoding="utf-8")
            src_texts.append(t)
        except Exception as e:
            failed.append(f"来源{i} {u} 抓取失败：{e}")
    if not src_texts:
        return {"error": "所有信源均抓取失败", "details": failed}
    sources_block = "\n".join(
        f"【来源{i + 1}】{t}" for i, t in enumerate(src_texts))

    # 3. LLM 深潜提取 + 反幻觉校验
    # 注意：prompt 内含 JSON 示例花括号，必须用 replace 而不是 format
    prompt = DEEP_PROMPT.replace("{sources}", sources_block)
    resp = client.chat.completions.create(
        model=P["model"], temperature=0.1,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}])
    report = json.loads(resp.choices[0].message.content)
    warnings = verify_report(report, src_texts)

    # 4. 存档
    result = {"name": name, "date": datetime.date.today().isoformat(),
              "sources": candidates[:len(src_texts)], "report": report,
              "verification_warnings": warnings,
              "fetch_failures": failed}
    out = OUT_DIR / f"{name}_report.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[M2] 深潜完成 → {out.name}；{len(warnings)} 条引句未过校验；{len(failed)} 个信源抓取失败")
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
