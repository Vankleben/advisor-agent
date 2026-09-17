"""
工具九：M2 导师深潜 v1.3
改动：1. 兼容旧格式卡片（homepage_candidates 为字符串数组时，直接跳过，走 fallback）
      2. fallback 触发条件改为"candidates 为空 *或* 全部抓取失败"，不再被 candidates 非空挡住
用法：python tools/advisor_deepdive.py 张三
      python tools/advisor_deepdive.py 张三 --url https://xxx.github.io
产出：data/deepdive/{name}_report.json        深潜报告
      data/deepdive/{name}_src{i}.txt         信源原文缓存
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import re
import sys
import datetime
from pathlib import Path

from fetch_common import get, strip_html
from llm_client import make_client, model_for
from store import find_card
from text_norm import flat

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUT_DIR = DATA_DIR / "deepdive"

MAX_SRC_CHARS = 8000
_PAGE_SEP = "\n\n@@PAGE@@\n\n"   # 多页抓取的页面分隔符（上层据此拆成多个信源）

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
    """抓正文（UA/SSL 降级/编码修正由 fetch_common 统一处理）；
    内容过短视为被拦截或 SPA 骨架，依次降级为无头浏览器渲染 / 多页抓取。"""
    r = get(url, timeout=20)
    text = strip_html(r.text)
    # 内容过短（被拦截）→ 降级 Chrome headless 渲染
    if len(text) < 50:
        try:
            from web_fetch import render_url
            print(f"⚠️ 内容过短({len(text)}字符)，降级 Chrome headless 渲染...")
            rendered = render_url(url, max_chars=8000, budget_ms=20000)
            if not rendered.get("error") and len(rendered.get("text", "")) > len(text):
                text = strip_html(rendered.get("text", ""))
                print(f"✅ 渲染后获取到 {len(text)} 字符")
        except Exception:
            pass
    # 仍是 SPA 骨架（React/Vue 站点只有导航壳，内容在子路由）→ 多页抓取全站
    if len(text) < 800:
        try:
            from web_fetch import render_site
            print(f"⚠️ 疑似 SPA 骨架({len(text)}字符)，多页抓取子页面...")
            site = render_site(url, max_pages=7)
            if not site.get("error") and len(site.get("text", "")) > len(text):
                # 每页单独作为一个信源（保留 source 编号语义），用 \n\n===\n\n 分隔由上层切分
                pages = site.get("pages") or []
                if pages:
                    text = _PAGE_SEP.join(f"[{p['url']}] {p['text']}" for p in pages)
                else:
                    text = re.sub(r"\s+", " ", site["text"]).strip()
                print(f"✅ 多页抓取完成：{len(pages)} 页 / {len(text)} 字符")
        except Exception as e:
            print(f"⚠️ 多页抓取失败：{e}")
    return text


def flatten(text: str) -> str:
    """比对用白化（唯一实现见 text_norm.flat）。"""
    return flat(text)


def load_card(name: str, site: str = "") -> dict:
    """按姓名取卡片（读取逻辑见 store.find_card）；找不到时抛 LookupError 由上层决定是否 fallback。"""
    card = find_card(name, site)
    if card is None:
        raise LookupError(f"卡片库中找不到 {name}，请先收录并生成卡片")
    return card


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
                fq = flatten(str(q))
                if fq in flats[src_idx]:
                    continue
                # 标的来源未命中时，检查是否在其他来源中命中（LLM 常把多页站点标错页码）
                others = [j + 1 for j, ft in enumerate(flats) if fq in ft]
                if others:
                    warnings.append(f"⚠️ {section}[{i}] 的 evidence 标为来源{src_idx + 1}，"
                                    f"实际在第 {others} 个来源中命中（引句真实，仅编号有误）")
                else:
                    warnings.append(f"⚠️ {section}[{i}] 的 evidence 在所有来源中均未找到："
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
            t = fetch_text(u)
            # 多页抓取结果：拆成独立信源，保留 LLM 标注 source 编号的语义
            if _PAGE_SEP in t:
                for i, part in enumerate(t.split(_PAGE_SEP), 1):
                    part = part.strip()
                    if not part:
                        continue
                    # 提取 [url] 前缀作为信源地址
                    m = re.match(r"\[(https?://[^\]]+)\]\s*(.*)", part, re.S)
                    src_urls.append(m.group(1) if m else f"{u}#p{i}")
                    src_texts.append((m.group(2) if m else part)[:MAX_SRC_CHARS])
            else:
                src_texts.append(t[:MAX_SRC_CHARS])
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
        model=model_for("fast"), temperature=0.1,
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
    client = make_client()
    print(json.dumps(run_deepdive(client, name, site, manual_url),
                     ensure_ascii=False, indent=2))