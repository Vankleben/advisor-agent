"""
M4：进组路径分析
输入老师名 → 读取其 M2 深潜报告 + 用户画像 → 产出需求侧/供给侧/行动方案
反幻觉规则：需求侧必须引用深潜报告里的 evidence 原文，无证据的判断不输出
用法（独立测试）：python tools/path_analysis.py 张三
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import sys
from pathlib import Path

from llm_client import make_client, model_for
from store import load_deepdive_report

BASE_DIR = Path(__file__).resolve().parent.parent
DEEPDIVE_DIR = BASE_DIR / "data" / "deepdive"

FENCE = chr(96) * 3   # markdown 代码围栏字符，动态构造避免显示问题

# 用户画像与硬件红线从 archive/profile.json 读取（唯一权威版本），禁止在此硬编码
from user_profile import format_profile, format_hardware  # noqa: E402

PROMPT = """你是进组路径分析员。用户是一名想进实验室的CS大三学生，我给他选定了目标老师。

铁律：
1. 需求侧（老师缺什么人）必须基于我提供的深潜报告原文，每条判断附 evidence 原句引用；
   报告里没有支撑的判断不要写；
2. 供给侧只对照用户画像列"已具备/可快速补齐/短期补不了"三档，不做无据评价；
3. 行动方案给1-2个敲门砖项目，必须过算力检查并标注设备A/B，超红线方案禁止出现；
   项目方向要能从需求侧判断里找到依据；
4. 输出用简洁中文。

【用户画像】
{profile}

【算力红线】
{hardware}

【目标老师的深潜报告】
{report}

输出JSON：
{{"demand": [{{"need": "老师缺什么样的人/技能", "evidence": "深潜报告原文", "note": ""}}],
  "supply": {{"ready": ["已具备"], "quick": ["可快速补齐"], "gap": ["短期补不了"]}},
  "actions": [{{"project": "敲门砖项目描述", "device": "A或B", "basis": "依据demand哪条", "steps": ["步骤"]}}],
  "summary": "一句话结论：值不值得主攻，从哪切入"}}"""


def strip_code_fence(text: str) -> str:
    """剥掉 LLM 输出可能带的 markdown 代码围栏"""
    if text.startswith(FENCE):
        text = text.split("\n", 1)[1]
        text = text.rsplit(FENCE, 1)[0]
    return text.strip()


def run_path_analysis(client, model, name: str, site: str = "") -> dict:
    # 1. 找深潜报告（读取逻辑见 store.load_deepdive_report）
    report = load_deepdive_report(name)
    if not report:
        return {"error": f"没有 {name} 的深潜报告，请先对该老师执行 M2 深潜（advisor_deepdive）"}

    # 2. 组 prompt 调 LLM
    prompt = PROMPT.format(profile=format_profile(), hardware=format_hardware(),
                           report=json.dumps(report.get("report", report),
                                             ensure_ascii=False))
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3)
    text = strip_code_fence(resp.choices[0].message.content.strip())
    result = json.loads(text)

    # 3. 落盘
    out = DEEPDIVE_DIR / f"{name}_path.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"name": name, "path": result, "saved": str(out)}


if __name__ == "__main__":
    # 独立测试模式
    client = make_client()
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if not name:
        print("用法：python tools/path_analysis.py 老师中文名")
        sys.exit(1)
    r = run_path_analysis(client, model_for("fast"), name)
    print(json.dumps(r, ensure_ascii=False, indent=2))
