"""
M1.5：对比视图
档一：全景表 —— 读所有卡片，按列输出（姓名/职称/方向/招生信号/有无深潜），纯本地不调LLM
档二：深度对比 —— 选2-5人，读卡片+深潜报告，调LLM打七项指标分，输出对比矩阵
用法（独立测试）：
  python tools/compare_advisors.py --panorama
  python tools/compare_advisors.py --compare 张三 李四
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEEPDIVE_DIR = DATA_DIR / "deepdive"
sys.path.insert(0, str(Path(__file__).resolve().parent))

FENCE = chr(96) * 3

# 用户画像从 archive/profile.json 读取（唯一权威版本），禁止在此硬编码
from user_profile import format_profile  # noqa: E402

COMPARE_PROMPT = """你是导师对比分析员。用户是一名CS大三学生，想横向对比几个目标老师。

铁律：
1. 每个老师的打分必须基于我提供的卡片和深潜报告原文，无证据的指标标0并注明"无数据"；
2. 七项指标每项1-5分，附一句理由，理由必须引用evidence原文片段；
3. 深潜报告不存在的老师，相关指标标0并注明"无深潜报告"；
4. 输出对比矩阵 + 总结建议。

七项指标说明：
- direction_match: 研究方向与用户画像（ML/LLM/CV/具身智能/AI4Science）的匹配程度
- recruitment_signal: 招生信号强度（有明确招收本科生=5，有意向=3，无信息=1）
- computational_relevance: 研究中计算/ML成分的占比
- info_transparency: 公开信息透明度（主页/论文/招生页等信息量）
- entry_feasibility: CS学生切入可行性
- group_activity: 组内近期活跃度（论文产出/动态更新）
- competition_level: 竞争门槛（分高=竞争大=难进）

【用户画像】
{profile}

【待对比老师数据】
{teachers_data}

输出JSON：
{{"matrix": [
  {{"name": "老师名",
    "scores": {{"direction_match": 0, "recruitment_signal": 0, "computational_relevance": 0, "info_transparency": 0, "entry_feasibility": 0, "group_activity": 0, "competition_level": 0}},
    "reasons": {{"direction_match": "理由", "recruitment_signal": "理由", "computational_relevance": "理由", "info_transparency": "理由", "entry_feasibility": "理由", "group_activity": "理由", "competition_level": "理由"}}
  }}
],
  "summary": "对比结论：推荐主攻谁、备选谁、放弃谁，各附一句理由"}}"""


def strip_code_fence(text: str) -> str:
    if text.startswith(FENCE):
        text = text.split("\n", 1)[1]
        text = text.rsplit(FENCE, 1)[0]
    return text.strip()


def panorama() -> str:
    """档一：全景表，读所有卡片输出精简列表"""
    rows = []
    for f in sorted(DATA_DIR.glob("cards_*.json")):
        site = f.stem.replace("cards_", "")
        with open(f, encoding="utf-8") as fp:
            cards = json.load(fp)["cards"]
        for c in cards:
            if c.get("skipped"):
                continue
            recruitment = c.get("recruitment") or {}
            interests = c.get("research_interests") or []
            if isinstance(interests, list):
                interests_str = "; ".join(str(x) for x in interests[:3])
            else:
                interests_str = str(interests)[:100]
            has_deepdive = (DEEPDIVE_DIR / f"{c.get('name')}_report.json").exists()
            rows.append({
                "name": c.get("name", ""),
                "site": site,
                "title": c.get("title", ""),
                "sections": c.get("sections", ""),
                "interests": interests_str,
                "recruitment": recruitment.get("level", ""),
                "has_deepdive": has_deepdive,
                "summary": (c.get("summary") or "")[:120],
            })
    return json.dumps(rows or "没有收录任何老师", ensure_ascii=False)


def deep_compare(client, model, names: list) -> dict:
    """档二：深度对比，读卡片+深潜报告，调LLM打七项指标分"""
    teachers_data = []
    for name in names:
        # 找卡片
        card = None
        for f in sorted(DATA_DIR.glob("cards_*.json")):
            with open(f, encoding="utf-8") as fp:
                for c in json.load(fp)["cards"]:
                    if c.get("name") == name:
                        card = c
                        break
            if card:
                break
        if not card:
            teachers_data.append({"name": name, "error": "未收录"})
            continue

        # 找深潜报告
        report_file = DEEPDIVE_DIR / f"{name}_report.json"
        report = None
        if report_file.exists():
            report = json.loads(report_file.read_text(encoding="utf-8"))
            report = report.get("report", report)

        teachers_data.append({
            "name": name,
            "card": {
                "title": card.get("title"),
                "sections": card.get("sections"),
                "research_interests": card.get("research_interests"),
                "recruitment": card.get("recruitment"),
                "summary": card.get("summary"),
            },
            "deepdive_report": report,
        })

    prompt = COMPARE_PROMPT.format(
        profile=format_profile(),
        teachers_data=json.dumps(teachers_data, ensure_ascii=False))

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3)
    text = strip_code_fence(resp.choices[0].message.content.strip())
    result = json.loads(text)

    out = DEEPDIVE_DIR / "compare_result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"names": names, "compare": result, "saved": str(out)}


if __name__ == "__main__":
    sys.path.insert(0, str(BASE_DIR))
    from config import PROVIDER, API_KEY
    from openai import OpenAI
    P = {"moonshot": ("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
         "deepseek": ("https://api.deepseek.com", "deepseek-chat")}[PROVIDER]
    client = OpenAI(api_key=API_KEY, base_url=P[0])

    if len(sys.argv) < 2:
        print("用法：")
        print("  python tools/compare_advisors.py --panorama        全景表")
        print("  python tools/compare_advisors.py --compare 张三 李四  深度对比（2-5人）")
        sys.exit(1)

    if sys.argv[1] == "--panorama":
        print(panorama())
    elif sys.argv[1] == "--compare":
        names = sys.argv[2:]
        if len(names) < 2:
            print("至少选2位老师")
            sys.exit(1)
        r = deep_compare(client, P[1], names)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"未知参数：{sys.argv[1]}")
        sys.exit(1)
